"""Opt-in hosted diagnostics, using fixed HTTPS providers and no RF tools."""
import json
import re
import urllib.request
import urllib.error
import socket
from marauder_ai import SYSTEM_PROMPT, _NoRedirect

PROVIDERS = {
    'OpenRouter Free': ('https://openrouter.ai/api/v1/chat/completions', 'openrouter/free'),
    'Gemini': ('https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
               'gemini-2.5-flash-lite'),
}


def validate(provider, model, key):
    if provider not in PROVIDERS:
        raise ValueError('Choose a supported cloud provider.')
    if not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('Enter a valid API key in Cloud settings.')
    if not re.fullmatch(r'[A-Za-z0-9_./:-]{1,160}', model):
        raise ValueError('Invalid cloud model identifier.')
    if provider == 'OpenRouter Free' and model != 'openrouter/free' and not model.endswith(':free'):
        raise ValueError('OpenRouter Free accepts only openrouter/free or :free models; no paid fallback.')
    if provider == 'Gemini' and model not in {'gemini-2.5-flash-lite', 'gemini-2.5-flash'}:
        raise ValueError('Choose gemini-2.5-flash-lite or gemini-2.5-flash. Check your account tier.')


def aggregate_context(lists):
    """Deliberately exclude names, addresses, GPS and event/command logs."""
    lines = []
    for kind in ['ap', 'sta', 'ble', 'host']:
        data = lists.get(kind, {})
        lines.append(f'{kind} count: {len(data)}')
        channels = {}
        signals = []
        for row in data.values():
            channel = str(row.get('channel', ''))
            if channel.isdigit() and 1 <= int(channel) <= 233:
                channels[channel] = channels.get(channel, 0) + 1
            try:
                signal = int(row.get('rssi', ''))
                if -127 <= signal <= 0:
                    signals.append(signal)
            except (ValueError, TypeError):
                pass
        if channels:
            lines.append('channel counts: ' + json.dumps(channels, sort_keys=True))
        if signals:
            lines.append(f'RSSI range: {min(signals)} to {max(signals)} dBm')
    return '\n'.join(lines)


def chat(messages, provider, model, api_key, consent=False, stream_cb=None, timeout=60):
    if not consent:
        raise ValueError('Enable cloud sharing in Cloud settings first.')
    validate(provider, model, api_key)
    turns = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for turn in messages[-8:]:
        if turn.get('role') not in {'user', 'assistant'} or not isinstance(turn.get('content'), str):
            raise ValueError('Invalid cloud conversation.')
        turns.append({'role': turn['role'], 'content': turn['content']})
    body = {'model': model, 'messages': turns, 'stream': False, 'max_tokens': 512}
    data = json.dumps(body).encode('utf-8')
    if len(data) > 65536:
        raise ValueError('Cloud context is too long. Start a new conversation.')
    request = urllib.request.Request(PROVIDERS[provider][0], data=data,
        headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(1048577)
        if len(raw) > 1048576:
            raise RuntimeError('Cloud response exceeded the size limit.')
        result = json.loads(raw)
        choices = result.get('choices', [])
        text = choices[0].get('message', {}).get('content') if choices else None
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError('Provider returned no answer; check model availability or content restrictions.')
    except urllib.error.HTTPError as error:
        messages = {401: 'API key rejected.', 403: 'Account or model access denied.',
                    402: 'Account credits/access required; no paid fallback was attempted.',
                    429: 'Free quota or rate limit reached. Retry later or choose local AI.'}
        raise RuntimeError(messages.get(error.code, f'Cloud provider error HTTP {error.code}.')) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        raise RuntimeError('Cloud request failed or timed out; no automatic retry was attempted.') from None
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise RuntimeError('Cloud provider returned an invalid response.') from None
    if stream_cb:
        stream_cb(text)
    return text
