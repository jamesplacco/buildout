"""The editor clients.

The Vim plugin runs headless (vim -Nu NONE -es) against stub engines: small shell scripts set as the
python option that print their arguments and exit 0 or 2. Emacs is not assumed to be installed, so
buildout.el and its ERT file are checked statically: balanced parentheses (ignoring strings, comments
and character literals), names, headers and the keys the docs promise.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / "editors"
VIM_PLUGIN = EDITORS / "buildout.vim"
EL = EDITORS / "buildout.el"
EL_TEST = EDITORS / "buildout-test.el"
VIM = shutil.which("vim") or "/usr/bin/vim"
needs_vim = pytest.mark.skipif(not Path(VIM).exists(), reason="vim is not installed")


def vq(text) -> str:
    """A Vim single-quoted string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def stub(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "buildout").mkdir(parents=True)
    (root / "sub").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'stub'\n")
    return root


@pytest.fixture
def ok_engine(tmp_path):
    return stub(tmp_path / "ok.sh", 'echo "cwd: $(pwd)"\necho "args: $*"\nfor a in "$@"; do echo "arg=$a"; done\n'
                                    'echo "+2.1% now -0.5 and 3% flat"\n')


@pytest.fixture
def bad_engine(tmp_path):
    return stub(tmp_path / "bad.sh", 'echo "engine broke on: $*" >&2\nexit 2\n')


def run_vim(tmp_path: Path, lines: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    script = tmp_path / "script.vim"
    script.write_text("\n".join(lines + ["qa!"]) + "\n")
    proc = subprocess.run([VIM, "-Nu", "NONE", "-i", "NONE", "-es", "-S", str(script)], cwd=tmp_path,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return proc


def dump(target: Path, expr: str = "getbufline(bufnr('buildout://out'), 1, '$')") -> str:
    return f"call writefile({expr}, {vq(target)})"


def setup(python, root=None, sync=True) -> list[str]:
    lines = [f"let g:buildout_python = {vq(python)}"]
    if root is not None:
        lines.append(f"let g:buildout_root = {vq(root)}")
    if sync:
        lines.append("let g:buildout_sync = 1")
    return lines + [f"source {VIM_PLUGIN}"]


# ---------------------------------------------------------------- Vim

@needs_vim
def test_vim_plugin_parses():
    proc = subprocess.run([VIM, "-Nu", "NONE", "-es", "-c", "source editors/buildout.vim", "-c", "qa!"], cwd=ROOT,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@needs_vim
def test_vim_results_buffer_shows_command_elapsed_and_output(tmp_path, repo, ok_engine):
    out, meta = tmp_path / "out.txt", tmp_path / "meta.txt"
    run_vim(tmp_path, setup(ok_engine, repo) + [
        "BuildoutThink Is AI a bubble?",
        dump(out),
        dump(meta, "[bufname('%'), &buftype, string(&modifiable), string(g:buildout_history)]"),
    ])
    lines = out.read_text().splitlines()
    assert lines[0] == "buildout think 'Is AI a bubble?'"
    assert lines[1] == f"in {repo}  with {ok_engine}"
    assert re.fullmatch(r"done in \d+\.\d\ds", lines[2])
    assert f"cwd: {repo}" in lines
    assert "args: -m buildout think Is AI a bubble?" in lines
    assert "arg=Is AI a bubble?" in lines
    name, buftype, modifiable, history = meta.read_text().splitlines()
    assert (name, buftype, modifiable) == ("buildout://out", "nofile", "0")
    assert history == "[['think', 'Is AI a bubble?']]"


@needs_vim
def test_vim_nonzero_exit_is_shown_in_the_buffer(tmp_path, repo, bad_engine):
    out = tmp_path / "out.txt"
    run_vim(tmp_path, setup(bad_engine, repo) + ["BuildoutBench", dump(out)])
    text = out.read_text()
    assert text.splitlines()[0] == "buildout bench"
    assert re.search(r"^failed: exit 2 after \d+\.\d\ds$", text, re.M)
    assert "engine broke on: -m buildout bench" in text
    assert "buildout: the command exited with status 2" in text


@needs_vim
def test_vim_missing_python_and_wrong_root(tmp_path, repo, ok_engine):
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    run_vim(tmp_path, setup("no-such-python-for-buildout", repo) + [
        "BuildoutDoctor", dump(first),
        f"let g:buildout_python = {vq(ok_engine)}",
        f"let g:buildout_root = {vq(repo / 'sub')}",
        "BuildoutDoctor", dump(second),
    ])
    assert "error: python executable not found: no-such-python-for-buildout" in first.read_text().splitlines()
    assert "error: no buildout package under " + str(repo / "sub") in second.read_text().splitlines()
    assert "args:" not in second.read_text()


@needs_vim
def test_vim_generic_command_quoting_rerun_yank_and_log(tmp_path, repo, ok_engine):
    out, yank, rerun, log = (tmp_path / n for n in ("out.txt", "yank.txt", "rerun.txt", "log.txt"))
    run_vim(tmp_path, setup(ok_engine, repo) + [
        'Buildout bonds --y10 4 --front "anch ored"',
        dump(out),
        "normal y",
        f"call writefile(split(@\", \"\\n\"), {vq(yank)})",
        "BuildoutHistory march 2009",
        "BuildoutRerun",
        dump(rerun),
        "BuildoutLog",
        dump(log, "getline(1, '$') + [bufname('%')]"),
    ])
    text = out.read_text()
    assert text.splitlines()[0] == "buildout bonds --y10 4 --front 'anch ored'"
    assert "arg=anch ored" in text
    assert yank.read_text().splitlines()[0] == f"cwd: {repo}"
    assert "args: -m buildout history march 2009" in rerun.read_text()
    log_lines = log.read_text().splitlines()
    assert log_lines[-1] == "buildout://log"
    assert log_lines[2].split(None, 1) == ["1", "history 'march 2009'"]
    assert log_lines[3].split(None, 1) == ["2", "bonds --y10 4 --front 'anch ored'"]


@needs_vim
def test_vim_root_walks_up_and_ticker_under_cursor(tmp_path, repo, ok_engine):
    notes = repo / "sub" / "notes.txt"
    notes.write_text("Buy $nvda, then BRK.B.\n")
    ta, fa = tmp_path / "ta.txt", tmp_path / "fa.txt"
    run_vim(tmp_path, setup(ok_engine) + [
        f"edit {notes}", "call cursor(1, 6)", "BuildoutTA", dump(ta),
        "wincmd p", "call cursor(1, 18)", "BuildoutFA", dump(fa),
    ])
    assert ta.read_text().splitlines()[0] == "buildout ta NVDA"
    assert f"cwd: {repo}" in ta.read_text().splitlines()
    assert fa.read_text().splitlines()[0] == "buildout fa BRK.B"


@needs_vim
def test_vim_bonds_arguments_and_validation(tmp_path, repo, ok_engine):
    good, bad = tmp_path / "good.txt", tmp_path / "bad.txt"
    run_vim(tmp_path, setup(ok_engine, repo) + [
        "BuildoutBonds 4 4.5% anchored", dump(good),
        "BuildoutBonds 4 x", dump(bad),
    ])
    assert good.read_text().splitlines()[0] == "buildout bonds --y10 4 --y30 4.5 --front anchored"
    bad_text = bad.read_text()
    assert "error: the 30-year yield must be a number in percent" in bad_text
    assert "args:" not in bad_text


@needs_vim
def test_vim_async_job_fills_the_buffer(tmp_path, repo, ok_engine):
    out = tmp_path / "out.txt"
    run_vim(tmp_path, setup(ok_engine, repo, sync=False) + [
        "if !has('job') && !has('nvim') | call writefile(['skip'], " + vq(out) + ") | qa! | endif",
        "BuildoutThink oil spikes",
        "let s:n = 0",
        "while getbufline(bufnr('buildout://out'), 3)[0] =~# '^running' && s:n < 200",
        "  sleep 50m",
        "  let s:n += 1",
        "endwhile",
        dump(out),
    ])
    text = out.read_text()
    if text.strip() == "skip":
        pytest.skip("this vim has no job support")
    assert re.search(r"^done in \d+\.\d\ds$", text, re.M)
    assert "args: -m buildout think oil spikes" in text


@needs_vim
def test_vim_highlighting_maps_and_namespace(tmp_path, repo, ok_engine):
    syn, maps, nomaps = tmp_path / "syn.txt", tmp_path / "maps.txt", tmp_path / "nomaps.txt"
    probe = "synIDattr(synID(search('^+2.1%', 'n'), {col}, 1), 'name')"
    cols = [1, 2, 11, 20]  # '+' and '2' in +2.1%, '-' in -0.5, '3' in 3%
    run_vim(tmp_path, setup(ok_engine, repo) + [
        "BuildoutThink x",
        dump(syn, "[" + ", ".join(probe.format(col=c) for c in cols) + ", synIDattr(synID(1, 1, 1), 'name')]"),
        dump(maps, "[maparg('<Leader>bt', 'n'), maparg('<Leader>bt', 'x'), maparg('<Leader>bw', 'n'), "
                   "string(filter(keys(g:), 'v:val =~? \"buildout\"')), "
                   "string(filter(getcompletion('', 'function'), 'v:val !~# \"^<SNR>\" && v:val =~? \"buildout\"')), "
                   "string(getcompletion('Buildout b', 'cmdline'))]"),
    ])
    assert syn.read_text().splitlines() == ["buildoutPositive", "buildoutPositive", "buildoutNegative",
                                            "buildoutPercent", "buildoutCommand"]
    t_normal, t_visual, w_normal, gvars, gfuncs, completion = maps.read_text().splitlines()
    assert (t_normal, t_visual, w_normal) == ("<Plug>(buildout-think)", "<Plug>(buildout-think)",
                                              "<Plug>(buildout-think-word)")
    assert sorted(eval(gvars)) == ["buildout_history", "buildout_python", "buildout_root", "buildout_sync",
                                   "loaded_buildout"]
    assert eval(gfuncs) == []
    assert {"bench", "bonds", "brain", "buyside"} <= set(eval(completion))
    run_vim(tmp_path, ["let g:buildout_no_mappings = 1", f"source {VIM_PLUGIN}",
                       dump(nomaps, "[maparg('<Leader>bt', 'n'), maparg('<Plug>(buildout-think)', 'n')]")])
    unmapped, plug = nomaps.read_text().splitlines()
    assert unmapped == "" and "think" in plug


# ---------------------------------------------------------------- Emacs (static)

def elisp_balance(src: str) -> tuple[bool, str]:
    """Check () and [] balance, skipping strings, ; comments, ?x character literals and backslash escapes."""
    stack: list[tuple[str, int]] = []
    i, n, line = 0, len(src), 1
    pairs = {")": "(", "]": "["}
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
        elif c == ";":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        elif c == '"':
            i += 1
            while i < n and src[i] != '"':
                if src[i] == "\\":
                    i += 1
                if i < n and src[i] == "\n":
                    line += 1
                i += 1
            if i >= n:
                return False, f"unterminated string near line {line}"
        elif c == "?" and (i == 0 or src[i - 1] in " \t\n()[]'`,"):
            i += 1
            if i < n and src[i] == "\\":
                i += 1
                # modifier prefixes such as \C- and \C-\M-
                while i + 1 < n and src[i] in "CMSHAs^" and src[i + 1] == "-":
                    i += 2
                    if i + 2 < n and src[i] == "\\" and src[i + 1] in "CMSHAs^" and src[i + 2] == "-":
                        i += 1
            # i is now at the character itself, which the step below skips
        elif c == "\\":
            i += 1
        elif c in "([":
            stack.append((c, line))
        elif c in ")]":
            if not stack or stack[-1][0] != pairs[c]:
                return False, f"unexpected {c!r} on line {line}"
            stack.pop()
        i += 1
    if stack:
        return False, f"unclosed {stack[-1][0]!r} from line {stack[-1][1]}"
    return True, "ok"


def test_elisp_balance_checker_itself():
    assert elisp_balance('(a "(" ?\\( ?\\) ?( ; )\n [b])')[0]
    assert elisp_balance("(memq c '(?\\s ?\\t ?\\\" ?\\C-x ?\\C-\\M-x ?\\\\))")[0]
    assert not elisp_balance("(a (b)")[0]
    assert not elisp_balance("(a))")[0]
    assert not elisp_balance("(a [b)]")[0]


@pytest.mark.parametrize("path", [EL, EL_TEST], ids=lambda p: p.name)
def test_elisp_parentheses_balance(path):
    ok, why = elisp_balance(path.read_text())
    assert ok, f"{path.name}: {why}"


@pytest.mark.parametrize("path", [EL, EL_TEST], ids=lambda p: p.name)
def test_elisp_names_are_prefixed(path):
    src = path.read_text()
    forms = re.findall(r"^\((defun|defcustom|defmacro|defsubst|defvar|defvar-local|defconst|defface|ert-deftest)\s+"
                       r"([^\s()]+)", src, re.M)
    assert forms
    bad = [name for _, name in forms if not name.startswith("buildout-")]
    assert not bad, bad
    assert re.search(r"-\*- lexical-binding: t; -\*-", src.splitlines()[0])


def test_elisp_package_shape():
    src = EL.read_text()
    assert "(provide 'buildout)" in src and src.rstrip().endswith(";;; buildout.el ends here")
    assert "(defgroup buildout nil" in src
    defuns = dict.fromkeys(re.findall(r"^\(defun (buildout-[\w-]+)", src, re.M))
    commands = re.findall(r"\(define-key map \"\w\" #'(buildout-[\w-]+)\)", src)
    assert len(commands) >= 20
    missing = [c for c in commands if c not in defuns]
    assert not missing, missing
    for name in ("buildout-run", "buildout-think", "buildout-think-at-point", "buildout-think-line", "buildout-bonds",
                 "buildout-history", "buildout-doctor", "buildout-bench", "buildout-ta", "buildout-fa",
                 "buildout-engine", "buildout-rerun", "buildout-log", "buildout-stop"):
        assert re.search(r";;;###autoload\n\(defun " + re.escape(name) + r" ", src), name
    assert "(define-derived-mode buildout-results-mode special-mode" in src
    assert "(define-minor-mode buildout-mode" in src and ":global t" in src
    assert "make-process" in src and ":sentinel" in src and "call-process" not in src
    assert "(defvar buildout-query-history nil" in src


@pytest.mark.parametrize("path", [VIM_PLUGIN, EL, EL_TEST], ids=lambda p: p.name)
def test_editor_files_house_style(path):
    text = path.read_text().lower()
    for banned in ("\u2014", "inter" + "section", "load" + "-bearing"):
        assert banned not in text, banned
