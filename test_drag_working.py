import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
from System.Windows.Forms import Form, DataObject, DragDropEffects, MethodInvoker
from System.Collections.Specialized import StringCollection
import webview
import time
import os
import threading
import ctypes

user32 = ctypes.windll.user32

class API:
    def __init__(self):
        self.w = None
        self.ready = False
        self.drag_result = None

    def on_ready(self):
        print('JS is ready and element rendered!')
        self.ready = True
        return True

    def start_drag(self, paths):
        print('start_drag received paths:', paths)
        sc = StringCollection()
        for p in paths:
            sc.Add(os.path.abspath(p))
        data = DataObject()
        data.SetFileDropList(sc)

        form = self.w.native
        def run_drag():
            print('Executing form.DoDragDrop on UI thread...')
            user32.ReleaseCapture()
            res = form.DoDragDrop(data, DragDropEffects.Copy | DragDropEffects.Move)
            print('DoDragDrop result is:', res)
            self.drag_result = str(res)

        form.Invoke(MethodInvoker(run_drag))
        return {'ok': True}

api = API()
html = '''
<!DOCTYPE html>
<html>
<body style="background:#141619;color:#fff;margin:0;padding:20px;">
  <div id="drag-item" draggable="true" style="width:200px;height:80px;background:#cbb8a0;color:#000;display:flex;align-items:center;justify-content:center;cursor:grab;user-select:none;font-weight:bold;">
    DRAG ME
  </div>
  <script>
    const el = document.getElementById('drag-item');
    el.addEventListener('dragstart', function(e) {
      console.log('dragstart fired');
      e.preventDefault();
      window.pywebview.api.start_drag(['test_drag_working.py']);
    });
    window.addEventListener('pywebviewready', function() {
      window.pywebview.api.on_ready();
    });
  </script>
</body>
</html>
'''

w = webview.create_window('Test Drag', html=html, js_api=api, width=350, height=250, x=300, y=300)
api.w = w

def run_sim():
    while not api.ready:
        time.sleep(0.1)
    time.sleep(0.5)
    print('Simulating mouse drag on (400, 350)...')
    user32.SetCursorPos(400, 350)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0) # Down
    time.sleep(0.2)
    # Move > 10 pixels to trigger HTML5 drag
    user32.mouse_event(0x0001, 30, 30, 0, 0)
    time.sleep(0.3)
    user32.mouse_event(0x0001, 30, 30, 0, 0)
    time.sleep(0.5)
    user32.mouse_event(0x0004, 0, 0, 0, 0) # Up
    time.sleep(1.0)
    print('Test finished! Result:', api.drag_result)
    w.destroy()

threading.Thread(target=run_sim, daemon=True).start()
webview.start()
