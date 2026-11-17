"""Check the real desktop renderer, both themes, forms and responsive layouts."""
import base64
import json
import tempfile
import time
from pathlib import Path
import webview
from app import API

root=Path(__file__).parent
api=API(tempfile.mkdtemp(prefix='theme-smoke-',dir=str(root)))
window=webview.create_window('Antares theme verification',(root/'index.html').as_uri(),js_api=api,width=1440,height=1000,hidden=False)
report={}

def cdp(method,params):
    from System import Action
    from webview.platforms.winforms import BrowserView
    control=BrowserView.instances[window.uid].webview
    holder={}
    def start():holder['task']=control.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.dumps(params))
    control.Invoke(Action(start))
    for _ in range(150):
        if holder['task'].IsCompleted:break
        time.sleep(.05)
    if not holder['task'].IsCompleted:raise TimeoutError('DevTools call timed out: '+method)
    return json.loads(str(holder['task'].Result))

def screenshot(name):
    window.evaluate_js('document.activeElement.blur()')
    time.sleep(.3)
    result=cdp('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
    (root/name).write_bytes(base64.b64decode(result['data']))

def run():
    try:
        for _ in range(80):
            time.sleep(.2)
            if window.evaluate_js("typeof snapshot!=='undefined' && snapshot!==null"):break
        assert window.evaluate_js("snapshot!==null"),'Desktop bridge did not populate data'
        print('Desktop bridge ready; checking six pages',flush=True)
        report['pages']={}
        for name in ['总览','请求记录','接入应用','上游连接','模型与价格','设置']:
            window.evaluate_js("Array.from(document.querySelectorAll('#navigation button')).find(x=>x.textContent.includes("+json.dumps(name)+")).click()")
            time.sleep(.12)
            report['pages'][name]=window.evaluate_js("({title:document.querySelector('h1').textContent,visible:document.querySelectorAll('.view:not([hidden])').length,overflow:document.documentElement.scrollWidth>innerWidth})")
            assert report['pages'][name]['title']==name and report['pages'][name]['visible']==1
            assert not report['pages'][name]['overflow'],name+' page overflow'
        window.evaluate_js("document.querySelector('#navigation button').click()")
        report['dark']=window.evaluate_js("({background:getComputedStyle(document.body).backgroundColor,canvas:getComputedStyle(document.documentElement).backgroundColor,cards:document.querySelectorAll('.card').length,theme:document.documentElement.dataset.theme})")
        assert report['dark']['cards']==5
        window.evaluate_js("applyTheme('dark')")
        screenshot('antares-airrail-dark.png')
        window.evaluate_js("document.getElementById('themeToggle').click()")
        report['light']=window.evaluate_js("({theme:document.documentElement.dataset.theme,canvas:getComputedStyle(document.documentElement).backgroundColor})")
        assert report['light']['theme']=='light' and report['light']['canvas']=='rgb(250, 250, 250)'
        screenshot('antares-airrail-light.png')
        window.evaluate_js("applyTheme('dark');renderOverview({requests:16,input_tokens:25000,output_tokens:8000,cached_tokens:12000,unknown_usage:1,costs:{CNY:0.42},daily:[{day:'2026-11-16',requests:5},{day:'2026-11-17',requests:11}],by_model:[{model:'test/model',requests:16,input_tokens:25000,output_tokens:8000}],by_client:[{client_name:'Test app',requests:16,input_tokens:25000,output_tokens:8000}]})")
        assert window.evaluate_js("document.querySelectorAll('.trend-row').length===2 && document.querySelectorAll('.rank-row').length===2"),'Populated overview did not render'
        window.evaluate_js("renderOverview(snapshot.overview||{})")
        report['responsive']={}
        for width in [900,768,390]:
            cdp('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':False})
            for idx in range(6):
                window.evaluate_js(f"document.querySelectorAll('#navigation button')[{idx}].click()")
                time.sleep(.08)
                assert window.evaluate_js('document.documentElement.scrollWidth<=innerWidth'),f'Page {idx} overflows at {width}px'
            report['responsive'][str(width)]='All six pages fit'
        cdp('Emulation.clearDeviceMetricsOverride',{})
        report['ok']=True
    except Exception as exc:
        report['ok']=False
        report['error']=repr(exc)
    finally:
        (root/'theme-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.destroy()

webview.start(run,private_mode=True,debug=False)
print(json.dumps(report,ensure_ascii=True))
raise SystemExit(0 if report.get('ok') else 1)
