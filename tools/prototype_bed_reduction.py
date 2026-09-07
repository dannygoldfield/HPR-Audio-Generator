"""Reproduce a selected native 11-second mix and attenuate only its bed."""
from __future__ import annotations
from array import array
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import tempfile
import wave

from hpr_audio_generator.config import load_config
from hpr_audio_generator.delivery import apply_constant_gain, measure_loudness, measure_loop, sha256
from fresh_eleven_batch import _fresh_mix


def pcm(path):
    with wave.open(str(path), 'rb') as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth(), f.getnframes()) == (48000, 2, 2, 528000)
        a = array('h'); a.frombytes(f.readframes(f.getnframes())); return a


def build(source_path: Path, config_path: Path, output_root: Path, bed_gain: float = .9):
    if bed_gain not in (.9, .75, .5):
        raise ValueError("Supported bed gains are 0.9, 0.75, and 0.5")
    bed_percent = round(bed_gain * 100)
    source = json.loads(source_path.read_text())
    if source['recipeId'] != 'AR-012' or source['durationSec'] != 11:
        raise ValueError('Requires the selected native eleven-second AR-012 composition')
    if sha256(Path(source['output']['path'])) != source['output']['sha256']:
        raise ValueError('Original delivered mix fingerprint changed')
    config = load_config(config_path)
    assets = {a.asset_id:a for a in config.assets}
    ingredients = source['ingredients']
    bed_target = float(source.get('mixScreening', {}).get('continuousBedTargetDbfs', -32))
    audio_id = f'AUD-BED{bed_percent}-' + hashlib.sha256((sha256(source_path)+f'|post-texture-bed-gain={bed_gain:g}|v1').encode()).hexdigest()[:10].upper()
    destination = output_root/audio_id
    if destination.exists():
        raise FileExistsError(destination)
    kwargs = dict(config=config, bed_asset=assets[ingredients['bed']['id']],
                  gesture_asset=assets[ingredients['gesture']['id']], music_asset=assets[ingredients['music']['id']],
                  seed=int(source['seed']), bed_target_dbfs=bed_target)
    original_raw = source_path.parent/'raw'/f"{source['audioId']}.raw.wav"
    with tempfile.TemporaryDirectory(prefix='hpr-bed-proof-') as tmp:
        tmp = Path(tmp)
        rebuilt = _fresh_mix(**kwargs, output=tmp/'original.wav', bed_stem_output=tmp/'bed.wav')
        if rebuilt != ingredients or sha256(tmp/'original.wav') != sha256(original_raw):
            raise ValueError('Original mix did not reproduce exactly; no derivative created')
        adjusted = _fresh_mix(**kwargs, output=tmp/'adjusted.wav', bed_gain=bed_gain, bed_stem_output=tmp/'bed90.wav')
        assert adjusted == ingredients
        old, new, bed, bed90 = [pcm(tmp/name) for name in ('original.wav','adjusted.wav','bed.wav','bed90.wav')]
        assert all(b90 == round(b*bed_gain) for b,b90 in zip(bed,bed90)), 'Bed gain mismatch'
        assert all(n-b90 == o-b for n,b90,o,b in zip(new,bed90,old,bed)), 'Foreground events changed'
        destination.mkdir(parents=True)
        raw = destination/f'{audio_id}.raw.wav'; raw.write_bytes((tmp/'adjusted.wav').read_bytes())
        output = destination/f'{audio_id}.wav'
        apply_constant_gain(raw, output, float(source['delivery']['gainDb']))
        level, loop = measure_loudness(output), measure_loop(output)
        assert level.true_peak_dbfs <= -1 and loop.click_check_passed
        result = dict(schemaVersion='1.0', candidateType='audio', audioId=audio_id,
                      recipeId=f'AR-012-BED{bed_percent}', durationSec=11, durationBank='11s',
                      sourceAudioId=source['audioId'], sourceManifest=str(source_path.resolve()),
                      sourceManifestSha256=sha256(source_path), sourceWavSha256=source['output']['sha256'],
                      sourceRawSha256=sha256(original_raw), sourceRawReproducedExactly=True,
                      seed=source['seed'], ingredients=ingredients, sourceBedTargetDbfs=bed_target,
                      bedLinearGain=bed_gain, bedReductionPercent=100-bed_percent, bedOffsetDb=20*math.log10(bed_gain),
                      bedGainStage='after periodic texture, before unchanged events',
                      foregroundSamplesIdentical=True, sourceMasterGainPreserved=True,
                      generatorCode={'path':str(Path(__file__).resolve()),'sha256':sha256(Path(__file__))},
                      mixingCode={'path':str(Path(__file__).with_name('fresh_eleven_batch.py').resolve()),'sha256':sha256(Path(__file__).with_name('fresh_eleven_batch.py'))},
                      generatorConfig={'path':str(config_path.resolve()),'sha256':sha256(config_path)},
                      sourceMasterGainDb=source['delivery']['gainDb'], loudness=asdict(level),
                      loopValidation=asdict(loop), humanAudioApproval=None, humanLoopApproval=None,
                      status='audio_only_review_pending', output={'path':str(output.resolve()),'sha256':sha256(output)},
                      raw={'path':str(raw.resolve()),'sha256':sha256(raw)},
                      sourceAssets=[{'id':assets[ingredients[r]['id']].asset_id,
                                     'sha256':sha256(assets[ingredients[r]['id']].path)} for r in ('bed','gesture','music')])
        (destination/f'{audio_id}.json').write_text(json.dumps(result,indent=2)+'\n')
        return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bed-gain',type=float,choices=[.9,.75,.5],default=.9,help='Remaining bed gain: .9 = 10%% lower, .75 = 25%% lower, .5 = 50%% lower')
    args=parser.parse_args()
    print(json.dumps(build(args.source_manifest,args.config,args.output,args.bed_gain),indent=2))
