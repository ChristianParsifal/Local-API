import csv
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class Monitor:
    def __init__(self, directory, protect, unprotect):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.protect, self.unprotect = protect, unprotect
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / 'monitor.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS objects(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,body TEXT);
        ''')
        self.settings = {'port':18765,'autostart':False,'close_to_tray':True,'usd_cny':'7.2','exchange_source':'manual','model_aliases':{},'budget_amount':'0','budget_currency':'CNY', **(self.get('settings','main') or {})}
        self.status = {'running':False,'host':'127.0.0.1','port':self.settings['port'],'url':f"http://127.0.0.1:{self.settings['port']}/v1",'error':None}
        for r in self.records():
            if r['status'] == 'in_progress':
                r.update(status='interrupted',finished_at=now(),error='Application stopped before request completed')
                self.record(r)

    def put(self, kind, obj):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?)',(kind,obj['id'],json.dumps(obj)))
            self.db.commit()
        return obj

    def get(self, kind, identifier):
        with self.lock:
            r=self.db.execute('SELECT body FROM objects WHERE kind=? AND id=?',(kind,identifier)).fetchone()
        return json.loads(r[0]) if r else None

    def objects(self, kind):
        with self.lock:
            rows=self.db.execute('SELECT body FROM objects WHERE kind=?',(kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def records(self):
        with self.lock:
            rows=self.db.execute('SELECT body FROM records ORDER BY rowid DESC').fetchall()
        return [json.loads(r[0]) for r in rows]

    def record(self,r):
        with self.lock:
            self.db.execute('INSERT INTO records VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(r['id'],json.dumps(r)))
            self.db.commit()

    def authenticate(self,key):
        digest=hashlib.sha256(key.encode()).hexdigest()
        return next((c for c in self.objects('clients') if c['enabled'] and secrets.compare_digest(c['key_hash'],digest)),None)

    def begin(self, client, endpoint, model):
        r=dict(id=secrets.token_hex(16),started_at=now(),finished_at=None,client_id=client['id'],client_name=client['name'],model=model,actual_model=None,endpoint=endpoint,status='in_progress',http_status=None,input_tokens=None,output_tokens=None,cached_tokens=None,reasoning_tokens=None,usage_known=False,cost=None,currency=None,price_id=None,duration_ms=None,error=None)
        self.record(r)
        return r

    def finish(self,r,status,code,usage,actual_model,started,error=None):
        r.update(status=status,http_status=code,finished_at=now(),duration_ms=round((time.monotonic()-started)*1000),error=error,actual_model=actual_model)
        r.update(usage)
        r['usage_known']=r['input_tokens'] is not None and r['output_tokens'] is not None
        if r['usage_known']:
            selected=self.settings.get('model_aliases',{}).get(actual_model or r['model'],actual_model or r['model'])
            prices=[p for p in self.objects('prices') if p['model']==selected and p['effective_at']<=r['started_at']]
            if not prices and actual_model != r['model']:
                requested=self.settings.get('model_aliases',{}).get(r['model'],r['model'])
                prices=[p for p in self.objects('prices') if p['model']==requested and p['effective_at']<=r['started_at']]
            if prices:
                p=max(prices,key=lambda x:x['effective_at'])
                cached=min(r['input_tokens'],r['cached_tokens'] or 0)
                raw=dict(p.get('raw_pricing') or {})
                for tier in sorted(raw.get('overrides',[]),key=lambda x:int(x.get('min_prompt_tokens',0))):
                    if r['input_tokens']>=int(tier.get('min_prompt_tokens',0)):raw.update(tier)
                rate=Decimal(p.get('usd_cny','1'))
                def unit(key,fallback):
                    value=Decimal(str(raw[key]))*rate*1000000 if key in raw else Decimal(p[fallback])
                    if not value.is_finite() or value<0:raise ValueError('Unknown pricing')
                    return value
                try:
                    creation=r.get('cache_creation_tokens',0)
                    if creation and 'input_cache_write' not in raw:raise ValueError('Unknown cache creation pricing')
                    onehour=r.get('cache_creation_1h_tokens',0)
                    if onehour and 'input_cache_write_1h' not in raw:raise ValueError('Unknown 1h cache pricing')
                    normal=max(0,r['input_tokens']-cached-creation)
                    cost=(Decimal(normal)*unit('prompt','input_price')+Decimal(cached)*unit('input_cache_read','cached_price')+Decimal(r['output_tokens'])*unit('completion','output_price')+Decimal(creation-onehour)*unit('input_cache_write','input_price')+Decimal(onehour)*(unit('input_cache_write_1h','input_price') if onehour else Decimal(0)))/Decimal(1000000)
                    r.update(cost=str(cost),currency=p['currency'],price_id=p['id'],estimate_scope='token_only')
                except (ValueError,ArithmeticError):r['pricing_error']='Unsupported or unknown pricing'
        self.record(r)

    def query(self,p):
        rows=self.records()
        for field in ('client_id','model','status'):
            if p.get(field): rows=[r for r in rows if r.get(field)==p[field]]
        if p.get('start'): rows=[r for r in rows if r['started_at'][:10]>=p['start'][:10]]
        if p.get('end'): rows=[r for r in rows if r['started_at'][:10]<=p['end'][:10]]
        page=max(1,int(p.get('page',1)));size=max(1,min(500,int(p.get('page_size',50))))
        return dict(items=rows[(page-1)*size:page*size],total=len(rows),page=page,page_size=size)

    def overview(self):
        rows=self.records();costs={}
        for r in rows:
            if r['cost'] is not None: costs[r['currency']]=str(Decimal(costs.get(r['currency'],'0'))+Decimal(r['cost']))
        def groups(field):
            result={}
            for r in rows:
                name=r.get(field) or 'unknown';g=result.setdefault(name,dict(name=name,requests=0,input_tokens=0,output_tokens=0,costs={}))
                g['requests']+=1;g['input_tokens']+=r['input_tokens'] or 0;g['output_tokens']+=r['output_tokens'] or 0
                if r['cost'] is not None: g['costs'][r['currency']]=str(Decimal(g['costs'].get(r['currency'],'0'))+Decimal(r['cost']))
            return list(result.values())
        month_costs={}
        for row in rows:
            if row['cost'] is not None and row['started_at'][:7]==now()[:7]:month_costs[row['currency']]=str(Decimal(month_costs.get(row['currency'],'0'))+Decimal(row['cost']))
        return dict(month_costs=month_costs,requests=len(rows),input_tokens=sum(r['input_tokens'] or 0 for r in rows),output_tokens=sum(r['output_tokens'] or 0 for r in rows),cached_tokens=sum(r['cached_tokens'] or 0 for r in rows),unknown_usage=sum(not r['usage_known'] for r in rows),costs=costs,by_model=groups('model'),by_client=groups('client_name'),daily=[dict(date=day,requests=len([r for r in rows if r['started_at'][:10]==day]),input_tokens=sum(r['input_tokens'] or 0 for r in rows if r['started_at'][:10]==day),output_tokens=sum(r['output_tokens'] or 0 for r in rows if r['started_at'][:10]==day)) for day in sorted({r['started_at'][:10] for r in rows})])

    def action(self,action,p):
        if action=='snapshot':
            latest={}
            for price in sorted(self.objects('prices'),key=lambda v:v['effective_at']):latest[price['model']]=price
            return dict(overview=self.overview(),records=self.query(p),clients=[{k:v for k,v in c.items() if k!='key_hash'} for c in self.objects('clients')],upstreams=[{**{k:v for k,v in u.items() if k!='secret'},'has_key':bool(u.get('secret'))} for u in self.objects('upstreams')],prices=list(latest.values()),settings=self.settings,status=self.status)
        if action=='save_upstream':
            old=self.get('upstreams',p.get('id','')) or {}
            u=dict(id=p.get('id') or secrets.token_hex(8),name=p['name'],base_url=p['base_url'].rstrip('/'),protocol=p.get('protocol','openai'),enabled=p.get('enabled',True),secret=self.protect(p['api_key'].encode()).hex() if p.get('api_key') else old.get('secret'))
            if not u['base_url'].startswith(('http://','https://')) or not u['secret']: raise ValueError('Valid URL and API key required')
            if u['enabled']:
                for other in self.objects('upstreams'):
                    if other['id']!=u['id'] and other['protocol']==u['protocol']:
                        other['enabled']=False;self.put('upstreams',other)
            self.put('upstreams',u);return {'id':u['id']}
        if action=='delete_upstream':
            with self.lock: self.db.execute('DELETE FROM objects WHERE kind=? AND id=?',('upstreams',p['id']));self.db.commit()
            return True
        if action=='create_client':
            key='ant-'+secrets.token_urlsafe(32);c=dict(id=secrets.token_hex(8),name=p['name'],key_prefix=key[:10],key_hash=hashlib.sha256(key.encode()).hexdigest(),enabled=True,created_at=now());self.put('clients',c)
            return dict(client={k:v for k,v in c.items() if k!='key_hash'},key=key)
        if action=='disable_client':
            c=self.get('clients',p['id'])
            if not c: raise ValueError('Unknown client')
            c['enabled']=False;self.put('clients',c);return True
        if action=='test_upstream':
            import httpx
            u=self.get('upstreams',p['id'])
            if not u: raise ValueError('Unknown upstream')
            key=self.unprotect(bytes.fromhex(u['secret'])).decode()
            base=u['base_url'];url=base+('/models' if base.endswith('/v1') else '/v1/models')
            headers={'x-api-key':key,'anthropic-version':'2023-06-01'} if u['protocol']=='anthropic' else {'Authorization':'Bearer '+key}
            response=httpx.get(url,headers=headers,timeout=20)
            return {'http_status':response.status_code,'reachable':response.is_success}
        if action=='backup':
            path=self.directory/('backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
            with self.lock:
                target=sqlite3.connect(path)
                try:self.db.backup(target)
                finally:target.close()
            return {'path':str(path)}
        if action=='sync_prices':
            import httpx
            rate=Decimal(str(self.settings['usd_cny']))
            try:
                if p.get('refresh_fx',True) is False:raise ValueError('Use configured exchange rate')
                fx=httpx.get('https://open.er-api.com/v6/latest/USD',timeout=20).json()
                candidate=Decimal(str(fx['rates']['CNY']))
                if candidate.is_finite() and candidate>0:
                    rate=candidate;self.settings.update(usd_cny=str(rate),exchange_source='https://open.er-api.com/v6/latest/USD',exchange_updated_at=now())
            except Exception:pass
            if not rate.is_finite() or rate<=0:raise ValueError('Positive USD/CNY rate required')
            response=httpx.get('https://openrouter.ai/api/v1/models',timeout=30);response.raise_for_status()
            count=0
            for m in response.json()['data']:
                raw=m.get('pricing') or {}
                try:
                    values={k:Decimal(str(raw[s])) for k,s in [('input_price','prompt'),('output_price','completion')]}
                    values['cached_price']=Decimal(str(raw.get('input_cache_read',raw['prompt'])))
                    if any(not d.is_finite() or d<0 for d in values.values()):continue
                except (KeyError,ValueError,ArithmeticError):continue
                price=dict(id=secrets.token_hex(8),model=m['id'],currency='CNY',effective_at=now(),source='https://openrouter.ai/api/v1/models',usd_cny=str(rate),raw_pricing=raw,estimate_scope='token_only')
                price.update({k:str(v*rate*1000000) for k,v in values.items()});price.update({'usd_'+k:str(v*1000000) for k,v in values.items()});self.put('prices',price);count+=1
            self.settings['price_updated_at']=now()
            self.put('settings',dict(id='main',**self.settings))
            return {'count':count,'usd_cny':str(rate),'source':'OpenRouter','updated_at':now()}
        if action=='save_price':
            raise ValueError('Prices are synchronized from OpenRouter; configure model_aliases in settings')
        if action=='save_settings':
            port=int(p.get('port',self.settings['port']))
            if not 1024<=port<=65535: raise ValueError('Port must be 1024..65535')
            if 'usd_cny' in p:
                rate=Decimal(str(p['usd_cny']))
                if not rate.is_finite() or rate<=0:raise ValueError('Positive USD/CNY rate required')
                p['usd_cny']=str(rate);self.settings['exchange_source']='manual'
            if 'model_aliases' in p and not isinstance(p['model_aliases'],dict):raise ValueError('model_aliases must be an object')
            self.settings.update({k:p[k] for k in ('autostart','close_to_tray','budget_amount','budget_currency','usd_cny','model_aliases') if k in p});self.settings['port']=port
            self.put('settings',dict(id='main',**self.settings));return self.settings
        if action=='query_records': return self.query(p)
        if action=='export_csv':
            path=self.directory/('requests-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.csv');rows=self.query({**p,'page':1,'page_size':500})['items']
            # Export every filtered page, without loading prompt or completion contents.
            total=self.query(p)['total']
            for page in range(2,(total+499)//500+1): rows.extend(self.query({**p,'page':page,'page_size':500})['items'])
            with path.open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for row in rows for k in row)) if rows else ['id']);w.writeheader();w.writerows(rows)
            return {'path':str(path)}
        raise ValueError('Unknown action: '+action)
