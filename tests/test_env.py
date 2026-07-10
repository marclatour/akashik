from __future__ import annotations

from akashik.env import load_env


def test_load_env_reads_local_then_global(tmp_path, monkeypatch) -> None:
    global_dir = tmp_path / "home" / ".akashik"
    global_dir.mkdir(parents=True)
    (global_dir / ".env").write_text(
        "# global secrets\n"
        "OPENAI_API_KEY=global-key\n"
        "GLOBAL_ONLY='quoted value'\n",
        encoding="utf-8",
    )
    local_dir = tmp_path / "project"
    local_dir.mkdir()
    (local_dir / ".env").write_text(
        "export OPENAI_API_KEY=local-key\n\nnot a pair\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(local_dir)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GLOBAL_ONLY", raising=False)

    loaded = load_env()

    import os

    assert len(loaded) == 2
    assert os.environ["OPENAI_API_KEY"] == "local-key"  # local beats global
    assert os.environ["GLOBAL_ONLY"] == "quoted value"


def test_load_env_never_overrides_process_environment(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "real-key")

    load_env(env_file)

    import os

    assert os.environ["OPENAI_API_KEY"] == "real-key"


def test_load_env_missing_files(tmp_path) -> None:
    assert load_env(tmp_path / "nope.env") == []
