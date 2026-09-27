"""标准 Skill 打包器必须包含 SKILL.md 引用的全部文件，尤其是 references/pacing.json。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGER_PATH = ROOT / 'scripts' / 'package_crowd_skill.py'
SKILL_SOURCE = ROOT / 'skills' / 'geo-crowd'
# 准活仓库里的实际下载包；同机开发时为 C:/Users/las/Codex/youhuo/public/geo/geo-crowd.zip
PUBLISHED_DOWNLOAD = ROOT.parent / 'youhuo' / 'public' / 'geo' / 'geo-crowd.zip'


def load_packager():
    spec = importlib.util.spec_from_file_location('package_crowd_skill', PACKAGER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def packager():
    return load_packager()


def build_archive(packager, directory):
    output = Path(directory) / 'geo-crowd.zip'
    report = packager.build(output=output)
    return output, report


def rewrite_archive(source, target, mutate):
    """把 source 复制成 target，并让 mutate(archive) 修改条目，用于构造损坏包。"""
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as doctored:
        for name in original.namelist():
            doctored.writestr(name, original.read(name))
    with zipfile.ZipFile(target, 'a', zipfile.ZIP_DEFLATED) as doctored:
        mutate(doctored)


def test_manifest_covers_every_skill_file(packager):
    files = packager.skill_files()
    assert 'references/pacing.json' in files
    assert sorted(files) == sorted(packager.REQUIRED_FILES), (
        'REQUIRED_FILES 与实际 Skill 目录不一致：新增或改名文件时必须同步打包清单'
    )


def test_versions_agree(packager):
    version = packager.read_versions()
    assert version.startswith('2026'), version
    assert version.encode('utf-8') in (SKILL_SOURCE / 'SKILL.md').read_bytes()


def test_build_includes_pacing_and_required_files(packager, tmp_path):
    output, report = build_archive(packager, tmp_path)
    with zipfile.ZipFile(output) as archive:
        names = sorted(archive.namelist())
        assert names == sorted('geo-crowd/' + name for name in packager.REQUIRED_FILES)
        assert not [name for name in names if '__pycache__' in name or name.endswith('.pyc')]
        pacing = json.loads(archive.read('geo-crowd/references/pacing.json').decode('utf-8'))
        assert pacing == {'questions_per_rest': 7, 'rest_seconds': 300, 'max_questions': None}
        for name in packager.REQUIRED_FILES:
            assert archive.read('geo-crowd/' + name) == (SKILL_SOURCE / name).read_bytes()
    assert report['version'] == packager.read_versions()
    assert report['sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_build_is_reproducible(packager, tmp_path):
    first, first_report = build_archive(packager, tmp_path / 'a')
    second, second_report = build_archive(packager, tmp_path / 'b')
    assert first_report['sha256'] == second_report['sha256']
    assert first.read_bytes() == second.read_bytes()


def test_build_does_not_touch_published_download(packager, tmp_path):
    if not PUBLISHED_DOWNLOAD.is_file():
        pytest.skip('本机没有准活下载包，跳过线上产物保护检查')
    before = hashlib.sha256(PUBLISHED_DOWNLOAD.read_bytes()).hexdigest()
    build_archive(packager, tmp_path)
    assert hashlib.sha256(PUBLISHED_DOWNLOAD.read_bytes()).hexdigest() == before


def test_verify_rejects_missing_pacing(packager, tmp_path):
    output, _ = build_archive(packager, tmp_path)
    doctored = tmp_path / 'missing-pacing.zip'
    with zipfile.ZipFile(output) as original, zipfile.ZipFile(doctored, 'w', zipfile.ZIP_DEFLATED) as target:
        for name in original.namelist():
            if name == 'geo-crowd/references/pacing.json':
                continue
            target.writestr(name, original.read(name))
    with pytest.raises(packager.SkillPackageError) as excinfo:
        packager.verify_archive(doctored)
    assert 'pacing.json' in str(excinfo.value)


def test_verify_rejects_junk_entry(packager, tmp_path):
    output, _ = build_archive(packager, tmp_path)
    doctored = tmp_path / 'junk.zip'
    rewrite_archive(output, doctored, lambda archive: archive.writestr(
        'geo-crowd/scripts/__pycache__/client.cpython-311.pyc', b'junk'))
    with pytest.raises(packager.SkillPackageError):
        packager.verify_archive(doctored)


def test_verify_rejects_content_mismatch(packager, tmp_path):
    output, _ = build_archive(packager, tmp_path)
    doctored = tmp_path / 'tampered.zip'
    with zipfile.ZipFile(output) as original, zipfile.ZipFile(doctored, 'w', zipfile.ZIP_DEFLATED) as target:
        for name in original.namelist():
            payload = original.read(name)
            if name == 'geo-crowd/references/pacing.json':
                payload = b'{"questions_per_rest": 5}'
            target.writestr(name, payload)
    with pytest.raises(packager.SkillPackageError):
        packager.verify_archive(doctored)


def test_verify_rejects_version_mismatch(packager, tmp_path):
    output, _ = build_archive(packager, tmp_path)
    with pytest.raises(packager.SkillPackageError) as excinfo:
        packager.verify_archive(output, expect_version='20260101-client0')
    assert '版本' in str(excinfo.value)


def test_verify_rejects_suspicious_file(packager, tmp_path):
    copied = tmp_path / 'skill'
    copied.mkdir()
    for name in packager.REQUIRED_FILES:
        target = copied / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((SKILL_SOURCE / name).read_bytes())
    (copied / 'references' / 'config.json').write_text('{"token": "x"}', encoding='utf-8')
    with pytest.raises(packager.SkillPackageError) as excinfo:
        packager.build(source=copied, output=tmp_path / 'suspicious.zip')
    assert 'config.json' in str(excinfo.value)


def test_published_download_package_is_complete(packager):
    if not PUBLISHED_DOWNLOAD.is_file():
        pytest.skip('本机没有准活下载包，跳过线上产物检查')
    report = packager.verify_archive(PUBLISHED_DOWNLOAD)
    assert len(report['files']) == len(packager.REQUIRED_FILES)
    assert report['pacing']['questions_per_rest'] == 7
    assert report['pacing']['rest_seconds'] == 300
    assert report['pacing']['max_questions'] is None


def test_pacing_rule_matches_documented_skill(packager):
    """节奏数值只在 pacing.json 维护，SKILL.md 的说明必须与之一致，否则客户端会照错的数字执行。"""
    pacing = json.loads((SKILL_SOURCE / 'references' / 'pacing.json').read_text(encoding='utf-8'))
    skill = (SKILL_SOURCE / 'SKILL.md').read_text(encoding='utf-8')
    assert f'每完成并成功提交 {pacing["questions_per_rest"]} 题' in skill
    assert f'休息 {pacing["rest_seconds"]} 秒' in skill
    assert '本机进度文件' in skill
    assert '不 release，不重新 claim' in skill
