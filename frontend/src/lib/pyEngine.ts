// In-browser engine: runs the real PathwayGPS Python backend (backend/app) under Pyodide.
// All source queries go directly from the browser to ClinVar/PubMed, Ensembl, UniProt, Reactome,
// Open Targets and CIViC (all CORS-enabled) through an httpx transport backed by fetch().

const PYODIDE_VERSION = '0.26.4';
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

const BOOTSTRAP = `
import os, json, asyncio
os.environ["PATHWAYGPS_DISK_CACHE"] = "0"
os.environ["PATHWAYGPS_SNAPSHOT_DIR"] = "/tmp/snapshots"
import httpx
from pyodide.http import pyfetch

FORBIDDEN = {"user-agent", "accept-encoding", "host", "content-length", "connection"}

class FetchTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        timeout = (request.extensions.get("timeout") or {}).get("read") or 40
        headers = {k: v for k, v in request.headers.items() if k.lower() not in FORBIDDEN}
        body = request.content or None
        kwargs = {"method": request.method, "headers": headers}
        if body:
            kwargs["body"] = body.decode("utf-8")
        try:
            resp = await asyncio.wait_for(pyfetch(str(request.url), **kwargs), timeout)
            content = await asyncio.wait_for(resp.bytes(), timeout)
        except asyncio.TimeoutError:
            raise httpx.ReadTimeout("timed out", request=request)
        except Exception as exc:
            raise httpx.ConnectError(str(exc), request=request)
        return httpx.Response(resp.status, headers={"content-type": resp.headers.get("content-type", "")}, content=content, request=request)

from app.core.http import HttpClient
from app.pipeline.service import AnalysisService
from app.pipeline.report import build_blocks, to_markdown, to_html

service = AnalysisService(HttpClient(transport=FetchTransport()))
`;

let ready: Promise<any> | null = null;
export type EngineStatus = (msg: string) => void;
let statusCb: EngineStatus = () => undefined;
export const onEngineStatus = (cb: EngineStatus) => { statusCb = cb; };

function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.onload = () => resolve(); s.onerror = () => reject(new Error('Could not load Pyodide from the CDN.'));
    document.head.appendChild(s);
  });
}

export function engine(): Promise<any> {
  return (ready ??= (async () => {
    statusCb('Downloading the Python runtime (one-time, ~10 MB)…');
    await loadScript(`${PYODIDE_URL}pyodide.js`);
    const py = await (window as any).loadPyodide({ indexURL: PYODIDE_URL });
    statusCb('Installing httpx…');
    await py.loadPackage(['micropip', 'ssl']);
    await py.runPythonAsync(`import micropip\nawait micropip.install(["httpx==0.27.2"])`);
    statusCb('Loading the PathwayGPS pipeline…');
    const zip = await fetch(`${import.meta.env.BASE_URL}py/app.zip`).then((r) => r.arrayBuffer());
    py.unpackArchive(zip, 'zip', { extractDir: '/home/pyodide' });
    await py.runPythonAsync(BOOTSTRAP);
    statusCb('');
    return py;
  })());
}

/** Call an async service method and return its JSON result. */
export async function call<T>(expr: string, args: Record<string, unknown> = {}): Promise<T> {
  const py = await engine();
  py.globals.set('__args', JSON.stringify(args));
  const out = await py.runPythonAsync(`
_a = json.loads(__args)
_r = ${expr}
if asyncio.iscoroutine(_r):
    _r = await _r
json.dumps(_r, default=str)
`);
  return JSON.parse(out) as T;
}
