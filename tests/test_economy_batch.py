import json
import pytest
from tests.test_local_mode import local_server, local_profile
from llm.providers.ollama import OllamaProvider
from llm.core.types import LLMInput, Message, Role
from llm.core.types import LLMOutput
from llm.cli.economy_batch import run_batch, validate_batch

@pytest.mark.parametrize('counts,expected', [({'prompt_eval_count':37,'eval_count':9},{'input_tokens':37,'output_tokens':9}),({},None),({'prompt_eval_count':True,'eval_count':-1},None)])
def test_usage_is_real_or_unknown(local_server,counts,expected):
    url,_,state=local_server
    state['usage_counts']=counts
    out=OllamaProvider(base_url=url,default_model='fixture').generate(LLMInput(messages=[Message(Role.USER,'hello')]))
    assert out.usage==expected

def request():
    return {'schemaVersion':1,'runId':'fixture','requests':[{'requestId':'one','taskId':'fixture','mode':'baseline','prompt':'hello','repetition':0,'expectedChecks':['exact:local ok']}]}

def test_batch_returns_usage_and_quality(local_server):
    url,_,state=local_server;state['usage_counts']={'prompt_eval_count':37,'eval_count':9}
    result=run_batch(OllamaProvider(base_url=url,default_model='fixture'),request())
    assert result['passed'] is True
    assert result['requests'][0]['usage']['input_tokens']==37
    assert result['requests'][0]['qualityPassed'] is True

@pytest.mark.parametrize('mutate',[lambda x:x.update(schemaVersion=2),lambda x:x['requests'][0].update(prompt='x'*16385),lambda x:x.update(requests=x['requests']*19)])
def test_batch_rejects_invalid_before_inference(mutate):
    data=request();mutate(data)
    with pytest.raises(ValueError):validate_batch(data)

@pytest.mark.parametrize('wire,correct', [('"local ok"',True),('"wrong"',False),('local ok',False),('{"answer":"local ok"}',False),('"local ok" trailing',False)])
def test_json_string_protocol_preserves_wire_and_exact_quality(wire,correct):
    class Provider:
        default_model='fixture'
        def generate(self,value):
            assert value.metadata=={'think':False,'format':{'type':'string'}}
            assert 'local ok' not in value.messages[0].content
            return LLMOutput(content=wire,model='fixture',usage={'input_tokens':25,'output_tokens':9})
    data=request()|{'responseFormat':'json-string'}
    result=run_batch(Provider(),data)
    assert result['passed'] is correct
    assert result['requests'][0]['rawContent']==wire
    assert result['requests'][0]['usage']['output_tokens']==9
    assert result['responseFormat']=='json-string'

def test_unknown_wire_format_rejected():
    with pytest.raises(ValueError):validate_batch(request()|{'responseFormat':'arbitrary'})
