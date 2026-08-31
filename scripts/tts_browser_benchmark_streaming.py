from __future__ import annotations

# This local benchmark embeds minified browser JavaScript on purpose.
# ruff: noqa: E501, E701, E702
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from scripts.tts_latency_benchmark import find_audio, load_env

HTML = r'''<!doctype html><meta charset="utf-8"><title>TTS browser benchmark</title>
<style>body{font:16px system-ui;max-width:760px;margin:40px auto}textarea{width:100%;height:110px}button{margin:12px 8px 12px 0;padding:12px}pre{background:#eee;padding:16px}</style>
<h1>TTS browser A/B benchmark</h1>
<textarea id="text">좋습니다. 그 경험에서 본인이 맡은 역할을 말씀해 주세요.</textarea><br>
<button id="batch">기존 전체 PCM 측정</button><button id="stream">스트리밍 측정</button>
<pre id="result">버튼을 눌러 측정하세요.</pre>
<script>
const processor = `class PCMPlayer extends AudioWorkletProcessor {
 constructor(){super();this.q=[];this.offset=0;this.first=false;this.rest=null;this.ended=false;this.underruns=0;this.buffered=0;this.started=false;this.startSamples=12000;this.port.onmessage=e=>{if(e.data==='end'){this.ended=true;this.port.postMessage({type:'stats',underruns:this.underruns});return}let u=new Uint8Array(e.data);if(this.rest!==null){let n=new Uint8Array(u.length+1);n[0]=this.rest;n.set(u,1);u=n;this.rest=null}if(u.length%2){this.rest=u[u.length-1];u=u.slice(0,-1)}let v=new DataView(u.buffer,u.byteOffset,u.byteLength),f=new Float32Array(u.length/2);for(let i=0;i<f.length;i++)f[i]=v.getInt16(i*2,true)/32768;this.q.push(f);this.buffered+=f.length;if(!this.started&&this.buffered>=this.startSamples)this.started=true}}
 process(i,o){let out=o[0][0],w=0;if(this.started)while(w<out.length&&this.q.length){let b=this.q[0],n=Math.min(out.length-w,b.length-this.offset);out.set(b.subarray(this.offset,this.offset+n),w);w+=n;this.offset+=n;this.buffered-=n;if(this.offset===b.length){this.q.shift();this.offset=0}}if(w&&!this.first){this.first=true;this.port.postMessage('first-render')}if(this.first&&!this.ended&&w===0)this.underruns++;return true}}
registerProcessor('pcm-player',PCMPlayer)`;
async function measure(mode){
 const output=document.querySelector('#result'); output.textContent='측정 중…';
 const ctx=new AudioContext({sampleRate:24000}); await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([processor],{type:'text/javascript'})));
 const node=new AudioWorkletNode(ctx,'pcm-player',{outputChannelCount:[1]});node.connect(ctx.destination);await ctx.resume();
 const started=performance.now(); let firstNetwork=null,firstRender=null,total=0,underruns=0,statsResolve;
 const stats=new Promise(resolve=>statsResolve=resolve),rendered=new Promise(resolve=>node.port.onmessage=e=>{if(e.data==='first-render'){firstRender=performance.now();resolve()}if(e.data?.type==='stats'){underruns=e.data.underruns;statsResolve()}});
 const response=await fetch('/'+mode+'?'+new URLSearchParams({text:document.querySelector('#text').value}));
 if(!response.ok)throw new Error(await response.text());const reader=response.body.getReader();
 while(true){const {done,value}=await reader.read();if(done)break;if(firstNetwork===null)firstNetwork=performance.now();total+=value.byteLength;node.port.postMessage(value.buffer,[value.buffer])}
 const completed=performance.now();node.port.postMessage('end');await Promise.all([Promise.race([rendered,new Promise((_,reject)=>setTimeout(()=>reject(new Error('render timeout')),5000))]),stats]);
 const result={mode,first_network_ms:+(firstNetwork-started).toFixed(1),first_render_ms:+(firstRender-started).toFixed(1),complete_ms:+(completed-started).toFixed(1),pcm_bytes:total,underrun_blocks:underruns,underrun_ms:+(underruns*128/24000*1000).toFixed(1),base_latency_ms:+ctx.baseLatency.toFixed(4)};
 output.textContent=JSON.stringify(result,null,2);window.lastBenchmark=result;window.benchmarkHistory=window.benchmarkHistory||[];window.benchmarkHistory.push(result);setTimeout(()=>ctx.close(),Math.max(1000,total/48000*1000+500));
}
for(const mode of ['batch','stream'])document.querySelector('#'+mode).onclick=()=>measure(mode).catch(e=>document.querySelector('#result').textContent=String(e));
</script>'''


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    env = load_env(Path(".env"))

    def log_message(self, fmt: str, *args: object) -> None:
        print(fmt % args, flush=True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, "text/html; charset=utf-8", HTML.encode())
            return
        if parsed.path not in {"/batch", "/stream"}:
            self._send(404, "text/plain", b"not found")
            return
        text = parse_qs(parsed.query).get("text", [""])[0]
        if not text or len(text) > 1000:
            self._send(400, "text/plain", b"invalid text")
            return
        try:
            if parsed.path == "/batch":
                self._batch(text)
            else:
                self._stream(text)
        except Exception as error:
            self._send(502, "text/plain", str(error).encode())

    def _request(self, text: str, stream: bool) -> Request:
        body = {"model": self.env["GEMINI_TTS_MODEL"],"input":"차분하고 자연스러운 한국어 면접관의 목소리로 말하세요.\n다음 문장만 한국어로 발화하세요: "+text,"response_format":{"type":"audio"},"generation_config":{"speech_config":[{"voice":"Kore"}]}}
        if stream: body["stream"] = True
        return Request("https://generativelanguage.googleapis.com/v1beta/interactions",data=json.dumps(body,ensure_ascii=False).encode(),headers={"x-goog-api-key":self.env["GEMINI_API_KEY"],"Api-Revision":"2026-05-20","Content-Type":"application/json","Accept":"text/event-stream"},method="POST")

    def _batch(self, text: str) -> None:
        with urlopen(self._request(text, False), timeout=60) as response:  # noqa: S310
            pcm=base64.b64decode(find_audio(json.loads(response.read())),validate=True)
        self._send(200,"application/octet-stream",pcm)

    def _stream(self, text: str) -> None:
        self.send_response(200);self.send_header("Content-Type","application/octet-stream");self.send_header("Cache-Control","no-store");self.end_headers()
        with urlopen(self._request(text, True), timeout=60) as response:  # noqa: S310
            for raw in response:
                line=raw.decode().strip()
                if not line.startswith("data:"):continue
                data=line[5:].strip()
                if not data or data=="[DONE]":continue
                event=json.loads(data);delta=event.get("delta",{})
                if event.get("event_type")=="step.delta" and delta.get("type")=="audio":
                    self.wfile.write(base64.b64decode(delta["data"],validate=True));self.wfile.flush()

    def _send(self,status: int,content_type: str,body: bytes) -> None:
        self.send_response(status);self.send_header("Content-Type",content_type);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)


if __name__ == "__main__":
    print("TTS browser benchmark: http://127.0.0.1:8020", flush=True)
    ThreadingHTTPServer(("127.0.0.1",8020),Handler).serve_forever()
