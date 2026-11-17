import json,time
from pathlib import Path
import webview
root=Path(__file__).parent
w=webview.create_window('Reference inspection','https://app.airrail.work/dashboard',width=1440,height=1000,hidden=True)
def inspect():
    try:
        for _ in range(45):
            time.sleep(.5)
            if w.evaluate_js("document.readyState==='complete' && document.body.innerText.length>100"): break
        result=w.evaluate_js("""JSON.stringify({url:location.href,text:document.body.innerText,html:document.documentElement.outerHTML,styles:Array.from(document.querySelectorAll('body,aside,nav,main,header,h1,h2,button,input,a,[class*=card],[class*=sidebar]')).slice(0,90).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.slice(0,90),bg:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color,border:getComputedStyle(e).borderRadius,font:getComputedStyle(e).fontFamily,size:getComputedStyle(e).fontSize}))})""")
        (root/'reference-inspection.json').write_text(result,encoding='utf-8')
        print('Reference inspection saved',flush=True)
    finally:w.destroy()
webview.start(inspect,private_mode=True)
