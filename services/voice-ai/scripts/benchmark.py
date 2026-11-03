"""Measure first *audio*, not HTTP headers; a final done event is mandatory."""
import argparse
import base64
import csv
import hashlib
import json
import math
import os
import statistics
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import httpx

URLS = {'elevenlabs': 'http://127.0.0.1:18080', 'cosyvoice': 'http://127.0.0.1:18081',
        'qwen': 'http://127.0.0.1:18082'}


def load_env():
    path = Path(__file__).resolve().parents[1] / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


def measure(client, url, text, voice_id, output, startup_buffer_ms=300):
    started = time.perf_counter()
    first = None
    pcm = bytearray()
    done = None
    request_id = None
    # Arrival times and cumulative audio support an ideal 24 kHz playback-buffer estimate.
    arrivals = []
    with client.stream('POST', url + '/v1/tts/stream',
                       json={'text': text, 'voice_id': voice_id}) as response:
        response.raise_for_status()
        header_ms = (time.perf_counter() - started) * 1000
        for line in response.iter_lines():
            if not line:
                continue
            item = json.loads(line)
            if item['type'] == 'start':
                request_id = item['request_id']
            elif item['type'] == 'audio':
                chunk = base64.b64decode(item['pcm_b64'], validate=True)
                if not chunk or len(chunk) % 2:
                    raise ValueError('Empty/misaligned audio event')
                now = time.perf_counter()
                if first is None:
                    first = now
                pcm.extend(chunk)
                arrivals.append((now - started, len(pcm) / 48000))
            elif item['type'] == 'error':
                raise RuntimeError(f"Provider failed: {item['error_type']}; request_id={request_id}")
            elif item['type'] == 'done':
                done = item['metrics']
    total = time.perf_counter() - started
    if not done or done['status'] != 'completed' or first is None:
        raise RuntimeError(f'Missing successful done event; request_id={request_id}')
    if len(pcm) != done['audio_bytes']:
        raise RuntimeError('Received PCM length differs from completion receipt')
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), 'wb') as handle:
        handle.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        handle.writeframes(pcm)
    duration = len(pcm) / 48000
    # Estimate maximum extra buffer needed after first audio to prevent a gap.
    # This excludes telephony/network jitter beyond this particular HTTP capture.
    previous_audio = 0
    required = 0
    for elapsed, cumulative in arrivals:
        required = max(required, elapsed - (first - started) - previous_audio)
        previous_audio = cumulative
    return {'request_id': request_id, 'http_headers_ms': header_ms,
            'client_ttfa_ms': (first - started) * 1000, 'client_total_ms': total * 1000,
            'audio_seconds': duration, 'client_rtf': total / duration,
            'chunks': len(arrivals), 'minimum_extra_buffer_ms': max(0, required * 1000),
            'buffer_budget_ms': startup_buffer_ms,
            'buffer_estimate_pass': required * 1000 <= startup_buffer_ms,
            'server': done, 'audio_file': str(output)}


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('--providers', nargs='+', choices=URLS, default=['cosyvoice', 'qwen'])
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--transcript-file', type=Path)
    parser.add_argument('--consent', action='store_true', help='Confirm voice owner consent')
    parser.add_argument('--eleven-voice-id', default=os.getenv('ELEVENLABS_VOICE_ID', ''))
    parser.add_argument('--texts', type=Path, default=Path(__file__).resolve().parents[1] / 'examples/korean.txt')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--buffer-ms', type=float, default=300)
    parser.add_argument('--out', type=Path, default=Path('reports') / datetime.now().strftime('%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0:
        parser.error('runs >= 1 and warmups >= 0 are required')
    if any(p != 'elevenlabs' for p in args.providers):
        if not args.reference or not args.transcript_file or not args.consent:
            parser.error('Local models require --reference, --transcript-file and --consent')
    key = os.getenv('LAB_API_KEY', '')
    if not key:
        parser.error('Set LAB_API_KEY or run scripts/configure.py')
    texts = [line.strip() for line in args.texts.read_text().splitlines() if line.strip()]
    if not texts:
        parser.error('Text file is empty')
    args.out.mkdir(parents=True, exist_ok=False)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'warmups': args.warmups,
              'runs_per_text': args.runs, 'text_sha256': hashlib.sha256(args.texts.read_bytes()).hexdigest(),
              'reference_sha256': hashlib.sha256(args.reference.read_bytes()).hexdigest() if args.reference else None,
              'providers': {}, 'samples': []}
    failure = False
    with httpx.Client(headers={'X-API-Key': key}, timeout=httpx.Timeout(600, connect=15),
                      trust_env=False) as client:
        # Sequential on a shared GPU: no cross-model contention during baseline tests.
        for provider in args.providers:
            url = os.getenv(provider.upper() + '_URL', URLS[provider]).rstrip('/')
            try:
                info = client.get(url + '/v1/info')
                info.raise_for_status()
                report['providers'][provider] = info.json()
                voice_id = args.eleven_voice_id
                if provider != 'elevenlabs':
                    with args.reference.open('rb') as handle:
                        response = client.post(url + '/v1/voices',
                                               files={'audio': (args.reference.name, handle, 'audio/wav')},
                                               data={'transcript': args.transcript_file.read_text().strip(),
                                                     'consent': 'true', 'name': 'benchmark-reference'})
                    response.raise_for_status()
                    voice_id = response.json()['voice_id']
                for index in range(args.warmups):
                    sample = measure(client, url, texts[0], voice_id,
                                     args.out / f'{provider}-warmup-{index}.wav', args.buffer_ms)
                    sample.update(provider=provider, phase='warmup', text_index=0, run=index, status='ok')
                    report['samples'].append(sample)
                for text_index, text in enumerate(texts):
                    for run in range(args.runs):
                        sample = measure(client, url, text, voice_id,
                                         args.out / f'{provider}-text{text_index}-run{run}.wav', args.buffer_ms)
                        sample.update(provider=provider, phase='measured', text_index=text_index, run=run, status='ok')
                        report['samples'].append(sample)
                        print(f'{provider} text={text_index} run={run}: TTFA={sample["client_ttfa_ms"]:.0f}ms '
                              f'RTF={sample["client_rtf"]:.3f} chunks={sample["chunks"]}', flush=True)
            except Exception as exc:
                failure = True
                report['samples'].append({'provider': provider, 'status': 'failed',
                                          'error_type': type(exc).__name__, 'error': str(exc)[:300]})
                print(f'{provider}: FAILED ({type(exc).__name__})', flush=True)
            finally:
                (args.out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    rows = []
    for provider in args.providers:
        samples = [s for s in report['samples'] if s['provider'] == provider
                   and s.get('phase') == 'measured' and s['status'] == 'ok']
        latencies = [s['client_ttfa_ms'] for s in samples]
        rows.append({'provider': provider, 'n': len(samples),
                     'ttfa_p50_ms': percentile(latencies, .5), 'ttfa_p95_ms': percentile(latencies, .95),
                     'mean_rtf': statistics.mean(s['client_rtf'] for s in samples) if samples else None,
                     'peak_allocated_mib': max((s['server']['gpu_peak_allocated_mib']
                                                for s in samples
                                                if 'gpu_peak_allocated_mib' in s['server']), default=None)})
    report['summary'] = rows
    (args.out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (args.out / 'summary.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'Report: {args.out}/results.json and summary.csv. p95 is descriptive for small n.')
    raise SystemExit(1 if failure else 0)


if __name__ == '__main__':
    main()
