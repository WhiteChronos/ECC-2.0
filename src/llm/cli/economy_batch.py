"""Explicit bounded local batch protocol for Token-Economy."""
import json
from pathlib import Path
import re
import time
from llm.core.types import LLMInput, Message, Role

def validate_batch(value: dict) -> dict:
    if not isinstance(value,dict) or set(value)!={"schemaVersion","runId","requests"} or type(value["schemaVersion"]) is not int or value["schemaVersion"]!=1:
        raise ValueError("Schema de lote invalido.")
    if not isinstance(value["runId"],str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",value["runId"]):raise ValueError("runId invalido.")
    requests=value["requests"]
    if not isinstance(requests,list) or not 1<=len(requests)<=18:raise ValueError("Lote deve conter entre 1 e 18 pedidos.")
    seen=set()
    for r in requests:
        if not isinstance(r,dict) or set(r)!={"requestId","taskId","mode","prompt","repetition","expectedChecks"}:raise ValueError("Pedido invalido.")
        for k in ("requestId","taskId"):
            if not isinstance(r[k],str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",r[k]):raise ValueError("Identificador invalido.")
        if r["requestId"] in seen:raise ValueError("requestId duplicado.")
        seen.add(r["requestId"])
        if r["mode"] not in ("baseline","optimized") or type(r["repetition"]) is not int or not 0<=r["repetition"]<3:raise ValueError("Modo ou repeticao invalido.")
        if not isinstance(r["prompt"],str) or not 1<=len(r["prompt"].encode("utf-8"))<=16384:raise ValueError("Prompt acima do limite.")
        checks=r["expectedChecks"]
        if not isinstance(checks,list) or not 1<=len(checks)<=100 or any(not isinstance(c,str) or not (c.startswith("exact:") or c.startswith("contains:")) or not c.split(":",1)[1] or len(c)>4096 for c in checks):raise ValueError("Criterios invalidos.")
    return value

def read_batch(file: str) -> dict:
    path=Path(file)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024*1024:raise ValueError("Arquivo de lote invalido.")
    return validate_batch(json.loads(path.read_text(encoding="utf-8-sig")))

def run_batch(provider,batch: dict) -> dict:
    validate_batch(batch)
    results=[]
    for r in batch["requests"]:
        started=time.perf_counter()
        try:
            output=provider.generate(LLMInput(messages=[Message(Role.USER,r["prompt"])],temperature=0,max_tokens=256,metadata={"think":False}))
            if not output.content.strip() or len(output.content.encode("utf-8"))>65536:raise ValueError("Resposta vazia ou excessiva.")
            checks=[output.content.strip()==c[6:] if c.startswith("exact:") else c[9:] in output.content for c in r["expectedChecks"]]
            results.append({k:r[k] for k in ("requestId","taskId","mode","repetition")}|{"content":output.content,"model":output.model,"usage":output.usage,"duration":time.perf_counter()-started,"qualityPassed":all(checks),"status":"completed","failureCode":None})
        except Exception as exc:
            results.append({k:r[k] for k in ("requestId","taskId","mode","repetition")}|{"content":"","model":provider.default_model,"usage":None,"duration":time.perf_counter()-started,"qualityPassed":False,"status":"failed","failureCode":type(exc).__name__})
            break
    return {"schemaVersion":1,"runId":batch["runId"],"requests":results,"passed":len(results)==len(batch["requests"]) and all(r["qualityPassed"] for r in results),"realInferenceVerified":bool(results) and all(r["status"]=="completed" for r in results),"parameters":{"temperature":0,"think":False,"max_tokens":256},"paidProviderFallback":False,"scope":"Real local responses only; no Codex billing attribution."}
