"""Exercise the real WebView2 renderer with an isolated empty data directory."""
import json
import tempfile
import time
from pathlib import Path
import webview
from app import API

report = {}
api = API(tempfile.mkdtemp(prefix='ui-smoke-', dir=str(Path(__file__).parent)))
root = Path(__file__).parent
window = webview.create_window('Antares UI verification', (root/'index.html').as_uri(), js_api=api, hidden=True)

def run():
    try:
        for _ in range(40):
            time.sleep(.25)
            ready = window.evaluate_js("document.readyState === 'complete' && !!window.pywebview")
            if ready:
                break
        report['title'] = window.evaluate_js('document.title')
        report['body'] = window.evaluate_js('document.body.innerText')
        report['bridge'] = window.evaluate_js("typeof window.pywebview.api.call")
        report['buttons'] = window.evaluate_js("Array.from(document.querySelectorAll('button')).map(x=>x.textContent)")
        report['pages'] = {}
        for name in ['总览','请求记录','接入应用','上游连接','模型与价格','设置']:
            window.evaluate_js("Array.from(document.querySelectorAll('#navigation button')).find(x=>x.textContent.includes("+json.dumps(name)+")).click()")
            time.sleep(.15)
            report['pages'][name] = window.evaluate_js('document.querySelector(\"main h1\").textContent')
        report['ok'] = report['bridge']=='function' and len(report['pages'])==6 and all(k==v for k,v in report['pages'].items())
    except Exception as exc:
        report['ok']=False
        report['error']=repr(exc)
    finally:
        (root/'ui-smoke-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.destroy()

webview.start(run,private_mode=True,debug=False)
raise SystemExit(0 if report.get('ok') else 1)
