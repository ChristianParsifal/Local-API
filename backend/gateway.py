import asyncio
import json
import threading
import time
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


def usage_from(data,usage):
    if not isinstance(data,dict): return None
    obj=data.get('response') if isinstance(data.get('response'),dict) else data
    u=obj.get('usage') or (obj.get('message') or {}).get('usage')
    if isinstance(u,dict):
        for target,keys in {'input_tokens':('prompt_tokens','input_tokens'),'output_tokens':('completion_tokens','output_tokens'),'cached_tokens':('cache_read_input_tokens',),'reasoning_tokens':()}.items():
            for key in keys:
                if isinstance(u.get(key),int): usage[target]=u[key]
        details=u.get('prompt_tokens_details') or u.get('input_tokens_details') or {}
        if isinstance(details.get('cached_tokens'),int):usage['cached_tokens']=details['cached_tokens']
        details=u.get('completion_tokens_details') or u.get('output_tokens_details') or {}
        if isinstance(details.get('reasoning_tokens'),int):usage['reasoning_tokens']=details['reasoning_tokens']
        # Anthropic input_tokens excludes both cache reads and cache creation.
        if 'cache_read_input_tokens' in u or 'cache_creation_input_tokens' in u:
            usage['input_tokens']=u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0)
            if u.get('cache_creation_input_tokens',0): usage['cache_creation_tokens']=u['cache_creation_input_tokens']
            creation=u.get('cache_creation') or {}
            if isinstance(creation.get('ephemeral_1h_input_tokens'),int):usage['cache_creation_1h_tokens']=creation['ephemeral_1h_input_tokens']
    return obj.get('model') or (obj.get('message') or {}).get('model')


class Gateway:
    def __init__(self,monitor):
        self.monitor=monitor;self.server=None;self.thread=None
        app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);self.app=app
        @app.api_route('/v1/{endpoint:path}',methods=['GET','POST'])
        async def forward(endpoint:str,request:Request):
            if endpoint not in ('chat/completions','completions','responses','models','messages'):
                return JSONResponse({'error':{'message':'Unsupported endpoint'}},404)
            key=request.headers.get('authorization','').removeprefix('Bearer ') or request.headers.get('x-api-key','')
            client=monitor.authenticate(key)
            if not client:return JSONResponse({'error':{'message':'Invalid local API key'}},401)
            raw=await request.body()
            try:body=json.loads(raw) if raw else {}
            except ValueError:return JSONResponse({'error':{'message':'Invalid JSON'}},400)
            if not isinstance(body,dict):return JSONResponse({'error':{'message':'JSON object required'}},400)
            if endpoint=='chat/completions' and body.get('stream') and monitor.settings.get('request_stream_usage',True):
                body.setdefault('stream_options',{}).setdefault('include_usage',True)
                raw=json.dumps(body).encode()
            protocol='anthropic' if endpoint=='messages' else 'openai'
            upstream=next((u for u in monitor.objects('upstreams') if u['enabled'] and u['protocol']==protocol),None)
            if not upstream:return JSONResponse({'error':{'message':'No enabled upstream for protocol'}},503)
            started=time.monotonic();r=monitor.begin(client,endpoint,body.get('model',''));usage={};actual=None
            transport=httpx.AsyncClient(timeout=httpx.Timeout(300,connect=15),follow_redirects=False)
            try:
                secret=monitor.unprotect(bytes.fromhex(upstream['secret'])).decode()
                headers={k:v for k,v in request.headers.items() if k.lower() not in ('host','authorization','x-api-key','content-length','connection','accept-encoding')}
                headers['accept-encoding']='identity'
                if protocol=='anthropic':headers['x-api-key']=secret;headers.setdefault('anthropic-version','2023-06-01')
                else:headers['authorization']='Bearer '+secret
                base=upstream['base_url'];url=base+('/' if base.endswith('/v1') else '/v1/')+endpoint
                if request.url.query:url+='?'+request.url.query
                response=await transport.send(transport.build_request(request.method,url,content=raw,headers=headers),stream=True)
            except Exception as exc:
                await transport.aclose();monitor.finish(r,'error',None,usage,actual,started,type(exc).__name__+': '+str(exc));return JSONResponse({'error':{'message':'Upstream connection failed'}},502)
            outheaders={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','transfer-encoding','connection','content-encoding')}
            if 'text/event-stream' not in response.headers.get('content-type',''):
                try:
                    content=await response.aread()
                    try:actual=usage_from(json.loads(content),usage)
                    except (ValueError,TypeError):pass
                    monitor.finish(r,'success' if response.status_code<400 else 'error',response.status_code,usage,actual,started)
                    return Response(content,status_code=response.status_code,headers=outheaders)
                except Exception as exc:
                    monitor.finish(r,'interrupted',response.status_code,usage,actual,started,str(exc));return JSONResponse({'error':{'message':'Upstream response interrupted'}},502)
                finally:await response.aclose();await transport.aclose()
            async def stream():
                nonlocal actual
                buffer=b'';status='interrupted';error='Stream ended before completion marker';complete=False
                try:
                    async for chunk in response.aiter_bytes():
                        buffer+=chunk
                        while b'\n' in buffer:
                            line,buffer=buffer.split(b'\n',1);line=line.strip()
                            if line.startswith(b'data:'):
                                value=line[5:].strip()
                                if value==b'[DONE]':complete=True
                                else:
                                    try:
                                        event=json.loads(value);actual=usage_from(event,usage) or actual
                                        if event.get('type') in ('response.completed','message_stop'):complete=True
                                    except (ValueError,TypeError):pass
                        # Bound only the parser; raw traffic continues unchanged.
                        if len(buffer)>4*1024*1024:buffer=b''
                        yield chunk
                    status=('success' if complete else 'interrupted') if response.status_code<400 else 'error'
                    error=None if complete else error
                except asyncio.CancelledError:
                    error='Client disconnected';raise
                except Exception as exc:error=type(exc).__name__+': '+str(exc);raise
                finally:
                    monitor.finish(r,status,response.status_code,usage,actual,started,error)
                    await response.aclose();await transport.aclose()
            return StreamingResponse(stream(),status_code=response.status_code,headers=outheaders)

    def start(self):
        if self.thread and self.thread.is_alive():return self.monitor.status
        port=self.monitor.settings['port'];self.monitor.status.update(port=port,url=f'http://127.0.0.1:{port}/v1',error=None)
        config=uvicorn.Config(self.app,host='127.0.0.1',port=port,log_level='warning',log_config=None,access_log=False,timeout_graceful_shutdown=5)
        self.server=uvicorn.Server(config)
        def run():
            try:self.server.run()
            except BaseException as exc:self.monitor.status['error']=str(exc)
            finally:self.monitor.status['running']=False
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        for _ in range(100):
            if self.server.started:break
            if not self.thread.is_alive():break
            time.sleep(.02)
        self.monitor.status['running']=self.server.started
        return self.monitor.status

    def stop(self):
        if self.server:self.server.should_exit=True
        if self.thread:self.thread.join(7)
        self.monitor.status['running']=bool(self.thread and self.thread.is_alive())
        return self.monitor.status
