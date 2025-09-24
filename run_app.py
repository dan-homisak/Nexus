# run_app.py
import threading, time, webbrowser, uvicorn, os

PORT = int(os.environ.get("NEXUS_PORT", "8000"))
URL  = f"http://127.0.0.1:{PORT}/?autoshutdown=1"   # query flag enables auto-quit on tab close

def _open_browser():
    # small delay so server is listening
    time.sleep(1.2)
    webbrowser.open(URL)

if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("backend.main:app", host="127.0.0.1", port=PORT, reload=False)
