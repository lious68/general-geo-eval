"""Build and verify the distributable geo-crowd Skill archive.

The file list is derived from the skill directory itself and then checked against
the files the Skill needs at run time, so a new reference file cannot be silently
left out and a rename cannot ship a broken ZIP.  Nothing is copied to the
published download copy unless --zhun-root is passed explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = ROOT / 'skills' / 'geo-crowd'
DEFAULT_OUTPUT = ROOT / 'dist' / 'geo-crowd.zip'
ARCHIVE_PREFIX = 'geo-crowd/'
DOWNLOAD_RELATIVE = Path('public') / 'geo' / 'geo-crowd.zip'
# Fixed timestamps keep the archive reproducible across checkouts and machines.
FIXED_TIMESTAMP = (2026, 9, 25, 0, 0, 0)

# Every file the Skill needs at run time.  SKILL.md links these references by
# relative path; a missing entry must fail the build instead of shipping a ZIP
# whose instructions point at a file that is not there.
REQUIRED_FILES = (
    'SKILL.md',
    'bind_windows.cmd',
    'scripts/client.py',
    'references/sample.json',
    'references/contract.md',
    'references/doubao.md',
    'references/screenshots.md',
    'references/fast-collection.md',
    'references/pacing.json',
)

# Never ship local build or OS artefacts, even if they appear in the skill tree.
EXCLUDED_PARTS = frozenset({'__pycache__', '.git', '.pytest_cache', '.mypy_cache', '.venv', 'venv', 'node_modules'})
EXCLUDED_SUFFIXES = ('.pyc', '.pyo', '.log', '.tmp')
EXCLUDED_NAMES = frozenset({'.DS_Store', 'Thumbs.db', 'desktop.ini'})

# Credentials and local runtime data must never enter a distributed archive.
SUSPICIOUS_NAME = re.compile(
    r'(^|[._-])(config\.json|credential|credentials|secret|secrets|key|keys|token|tokens|id_rsa|id_ed25519)([._-]|$)'
    r'|\.(env|db|sqlite|sqlite3|pem|pfx|p12|kdbx)$',
    re.IGNORECASE,
)

PACING_KEYS = ('questions_per_rest', 'rest_seconds', 'max_questions')
SKILL_VERSION = re.compile(r'工具版本[：:]\s*([^\s。，,；;]+)')
CLIENT_VERSION = re.compile(r"^VERSION\s*=\s*'([^']+)'", re.MULTILINE)


class SkillPackageError(Exception):
    """The Skill archive does not match what the Skill needs."""


def skill_files(source=SKILL_SOURCE):
    """Return the sorted archive-relative paths that belong in the package."""
    if not source.is_dir():
        raise SkillPackageError(f'Skill 目录不存在：{source}')
    files = []
    for path in source.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.suffix.lower() in EXCLUDED_SUFFIXES or relative.name in EXCLUDED_NAMES:
            continue
        files.append(relative.as_posix())
    return sorted(files, key=str.lower)


def find_suspicious(files):
    """Return the archive paths that look like credentials or local runtime data."""
    return [relative for relative in files
            if any(SUSPICIOUS_NAME.search(part) for part in relative.split('/'))]


def read_versions(source=SKILL_SOURCE):
    """Read the Skill version from SKILL.md and client.py and require them to agree."""
    skill_text = (source / 'SKILL.md').read_text(encoding='utf-8')
    client_text = (source / 'scripts' / 'client.py').read_text(encoding='utf-8')
    skill_match = SKILL_VERSION.search(skill_text)
    client_match = CLIENT_VERSION.search(client_text)
    if not skill_match:
        raise SkillPackageError('SKILL.md 缺少“工具版本：…”标记，无法核对版本')
    if not client_match:
        raise SkillPackageError('scripts/client.py 缺少 VERSION 常量，无法核对版本')
    skill_version, client_version = skill_match.group(1), client_match.group(1)
    if skill_version != client_version:
        raise SkillPackageError(f'SKILL.md 版本 {skill_version} 与 client.py VERSION {client_version} 不一致')
    return skill_version


def _check_pacing(payload, origin):
    try:
        config = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SkillPackageError(f'{origin} 不是可解析的 UTF-8 JSON：{exc}') from None
    if not isinstance(config, dict):
        raise SkillPackageError(f'{origin} 顶层必须是 JSON 对象')
    missing = [key for key in PACING_KEYS if key not in config]
    if missing:
        raise SkillPackageError(f'{origin} 缺少字段：{", ".join(missing)}')
    per_rest, rest_seconds, max_questions = (config[key] for key in PACING_KEYS)
    if not isinstance(per_rest, int) or isinstance(per_rest, bool) or per_rest < 1:
        raise SkillPackageError(f'{origin} questions_per_rest 必须是 >=1 的整数，实际 {per_rest!r}')
    if not isinstance(rest_seconds, int) or isinstance(rest_seconds, bool) or rest_seconds < 0:
        raise SkillPackageError(f'{origin} rest_seconds 必须是 >=0 的整数，实际 {rest_seconds!r}')
    if max_questions is not None and (not isinstance(max_questions, int) or isinstance(max_questions, bool)):
        raise SkillPackageError(f'{origin} max_questions 必须是 null 或整数，实际 {max_questions!r}')
    return config


def verify_archive(output, source=SKILL_SOURCE, expect_version=None):
    """Verify a built archive against the Skill directory and return a report."""
    output = Path(output)
    if not output.is_file():
        raise SkillPackageError(f'归档不存在：{output}')
    expected = skill_files(source)
    missing_required = [name for name in REQUIRED_FILES if name not in expected]
    if missing_required:
        raise SkillPackageError('Skill 目录缺少必需文件：' + ', '.join(missing_required))
    version = read_versions(source)
    if expect_version and version != expect_version:
        raise SkillPackageError(f'版本应为 {expect_version}，实际 {version}')

    with zipfile.ZipFile(output) as archive:
        broken = archive.testzip()
        if broken:
            raise SkillPackageError(f'归档 CRC 校验失败：{broken}')
        names = archive.namelist()
        outside = [name for name in names if not name.startswith(ARCHIVE_PREFIX)]
        if outside:
            raise SkillPackageError('归档包含顶层目录之外的条目：' + ', '.join(sorted(outside)))
        actual = sorted((name[len(ARCHIVE_PREFIX):] for name in names), key=str.lower)
        if actual != expected:
            missing = [name for name in expected if name not in actual]
            extra = [name for name in actual if name not in expected]
            detail = []
            if missing:
                detail.append('缺少 ' + ', '.join(missing))
            if extra:
                detail.append('多出 ' + ', '.join(extra))
            raise SkillPackageError('归档文件清单与 Skill 目录不一致：' + '；'.join(detail))
        for name in actual:
            relative = ARCHIVE_PREFIX + name
            payload = archive.read(relative)
            if not payload:
                raise SkillPackageError(f'归档条目为空：{relative}')
            if payload != (source / name).read_bytes():
                raise SkillPackageError(f'归档条目与 Skill 源文件不一致：{relative}')
        pacing = _check_pacing(archive.read(ARCHIVE_PREFIX + 'references/pacing.json'), '归档 references/pacing.json')
        if version.encode('utf-8') not in archive.read(ARCHIVE_PREFIX + 'SKILL.md'):
            raise SkillPackageError(f'归档 SKILL.md 中找不到版本 {version}')
    suspicious = find_suspicious(expected)
    if suspicious:
        raise SkillPackageError('Skill 目录包含疑似凭据或本机数据，禁止打包：' + ', '.join(suspicious))
    return {
        'path': str(output),
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'version': version,
        'files': expected,
        'pacing': pacing,
    }


def build(source=SKILL_SOURCE, output=DEFAULT_OUTPUT, timestamp=FIXED_TIMESTAMP):
    """Write the archive from the Skill directory, then verify what was written."""
    files = skill_files(source)
    missing = [name for name in REQUIRED_FILES if name not in files]
    if missing:
        raise SkillPackageError('Skill 目录缺少必需文件：' + ', '.join(missing))
    suspicious = find_suspicious(files)
    if suspicious:
        raise SkillPackageError('Skill 目录包含疑似凭据或本机数据，禁止打包：' + ', '.join(suspicious))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            entry = zipfile.ZipInfo(ARCHIVE_PREFIX + relative, date_time=timestamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, (source / relative).read_bytes())
    return verify_archive(output, source=source)


def copy_to_download(report, zhun_root, allow_overwrite=False):
    """Copy a verified archive onto a zhun checkout's public download path."""
    zhun_root = Path(zhun_root)
    if not (zhun_root / 'geo_crowd.py').is_file():
        raise SkillPackageError('指定目录不是带 GEO 模块的准活仓库')
    destination = zhun_root / DOWNLOAD_RELATIVE
    if destination.is_file() and not allow_overwrite:
        current = hashlib.sha256(destination.read_bytes()).hexdigest()
        if current != report['sha256']:
            raise SkillPackageError(
                f'已存在的下载包 {destination} 内容不同（当前 {current}）。'
                '确认要用新包替换后加 --allow-overwrite，不要用旧打包器覆盖线上包。'
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report['path'], destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='打包并校验 GEO 众包 Skill 归档')
    parser.add_argument('--zhun-root', type=Path, help='带 GEO 模块的准活仓库根目录，校验通过后复制下载包')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT, help=f'归档输出位置，默认 {DEFAULT_OUTPUT}')
    parser.add_argument('--source', type=Path, default=SKILL_SOURCE, help='Skill 源目录')
    parser.add_argument('--verify', type=Path, help='只校验指定归档，不重新打包')
    parser.add_argument('--expect-version', help='要求归档版本等于该值')
    parser.add_argument('--allow-overwrite', action='store_true', help='允许替换内容不同的已发布下载包')
    args = parser.parse_args(argv)
    try:
        if args.verify:
            report = verify_archive(args.verify, source=args.source, expect_version=args.expect_version)
        else:
            report = build(source=args.source, output=args.output)
            if args.expect_version and report['version'] != args.expect_version:
                raise SkillPackageError(f'版本应为 {args.expect_version}，实际 {report["version"]}')
        print(report['path'])
        print('SHA256: ' + report['sha256'])
        print(f'版本: {report["version"]}')
        print(f'文件数: {len(report["files"])}')
        for name in report['files']:
            print('  ' + name)
        print('pacing: ' + json.dumps(report['pacing'], ensure_ascii=False, sort_keys=True))
        if args.zhun_root:
            destination = copy_to_download(report, args.zhun_root, allow_overwrite=args.allow_overwrite)
            print('已复制到: ' + str(destination))
    except SkillPackageError as exc:
        print('校验失败：' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
