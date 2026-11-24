"""Optional Chrome + Node smoke test. Does not call any cloud action."""
import argparse
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8766/')
    args = parser.parse_args()
    chrome = os.getenv('CHROME_BIN') or shutil.which('google-chrome') or shutil.which('chromium')
    if not chrome:
        for candidate in ('C:/Program Files/Google/Chrome/Application/chrome.exe',
                          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'):
            if Path(candidate).exists():
                chrome = candidate
                break
    if not chrome or not shutil.which('node'):
        raise SystemExit('Optional UI QA requires Chrome and Node 20+ (WebSocket support).')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    output = ROOT / '.local/ui-validation'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='agentsphere-studio-ui-') as profile:
        process = subprocess.Popen([chrome, '--headless=new', '--disable-gpu', '--no-first-run',
            '--disable-background-networking', '--remote-debugging-address=127.0.0.1',
            f'--remote-debugging-port={port}', '--user-data-dir=' + profile, args.url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            endpoint = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    opener.open(endpoint + '/json/version', timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            result = subprocess.run(['node', '--experimental-websocket',
                str(ROOT / 'scripts/browser_qa.mjs'), endpoint, str(output)],
                capture_output=True, text=True, encoding='utf-8', timeout=90)
            print(result.stdout)
            print(result.stderr)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
            time.sleep(1)


if __name__ == '__main__':
    main()
