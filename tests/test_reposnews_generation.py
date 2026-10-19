from unittest.mock import Mock,patch
from app.reposnews_generation import generate_json


def test_existing_text_provider_fallback_works_when_native_vision_provider_fails():
    unavailable=Mock(ok=False,status_code=503)
    success=Mock(ok=True,status_code=200);success.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"title":"verified result"}'}}]}
    config={'api':{'base_url':'https://generativelanguage.googleapis.com/v1beta/openai','api_key':'fixture-gemini','model':'fixture-model'},
        'openrouter':{'base_url':'https://openrouter.ai/api/v1','api_key':'fixture-router','model':'fixture-approved-model'}}
    with patch('app.web_search._gemini_key',return_value='fixture-gemini'),patch('app.web_search._model',return_value='fixture-flash'),patch('app.model_router.model_for',return_value='fixture-primary'),patch('app.config.load',return_value=config),patch('app.reposnews_generation.requests.post',side_effect=[unavailable,unavailable,unavailable,success]) as post:
        result=generate_json('Write a JSON draft using these verified facts')
    assert result=={'title':'verified result'}
    assert post.call_args.args[0]=='https://openrouter.ai/api/v1/chat/completions'
    assert post.call_args.kwargs['allow_redirects'] is False
    assert post.call_count==4


def test_truncated_generation_is_not_accepted_as_complete():
    truncated=Mock(ok=True,status_code=200);truncated.json.return_value={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{"title":"partial"}'}]}}]}
    import pytest
    with patch('app.web_search._gemini_key',return_value='fixture-gemini'),patch('app.web_search._model',return_value='fixture-flash'),patch('app.model_router.model_for',return_value='fixture-primary'),patch('app.config.load',return_value={}),patch('app.reposnews_generation.requests.post',return_value=truncated):
        with pytest.raises(ValueError):generate_json('draft')


def test_existing_fallback_receives_images_without_losing_evidence():
    unavailable=Mock(ok=False,status_code=503)
    success=Mock(ok=True,status_code=200);success.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"selected":[0,1]}'}}]}
    config={'api':{'base_url':'https://generativelanguage.googleapis.com/v1beta/openai','api_key':'fixture-key'}}
    parts=[{'inlineData':{'mimeType':'image/jpeg','data':'fixture-image'}}]
    with patch('app.web_search._gemini_key',return_value='fixture-key'),patch('app.web_search._model',return_value='fixture-flash'),patch('app.model_router.model_for',return_value='fixture-primary'),patch('app.config.load',return_value=config),patch('app.reposnews_generation.requests.post',side_effect=[unavailable,unavailable,success]) as post:
        assert generate_json('Select real frames',parts)=={'selected':[0,1]}
    message=post.call_args.kwargs['json']['messages'][1]['content']
    assert message[1]['image_url']['url']=='data:image/jpeg;base64,fixture-image'
    assert post.call_args.kwargs['allow_redirects'] is False


def test_unsupported_media_does_not_degrade_to_text_only():
    import pytest
    with patch('app.web_search._gemini_key',return_value=''),patch('app.web_search._model',return_value='fixture-flash'),patch('app.model_router.model_for',return_value='fixture-primary'),patch('app.config.load',return_value={'api':{'api_key':'fixture-key'}}),patch('app.reposnews_generation.requests.post') as post:
        with pytest.raises(ValueError):generate_json('Analyze video',[{'inlineData':{'mimeType':'video/mp4','data':'fixture'}}])
    post.assert_not_called()
