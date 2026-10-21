"""Capture the dashboard's OrcaRouter provider panel as PR evidence.

The verification harness runs this file against the real FastAPI dashboard the
patch adds: uvicorn serves the checked-out app, headless Chromium drives the
real provider panel, and the screenshots plus the manifest that the evidence
validator reads are written to ``orca-evidence/``. No fixture HTML and no
pre-rendered image is involved.

The test is skipped unless a real OrcaRouter key is present, because the panel
must be populated from the authoritative live catalog rather than from the
offline seed.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

CATALOG_URL = "https://api.orcarouter.ai/v1/models?capability=chat"
VIEWPORT = {"width": 1280, "height": 900}
CHROMIUM = "/usr/bin/chromium"

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "orca-evidence"

DROPDOWN_METRICS = """() => {
    const trigger = document.getElementById('orcarouter-model-trigger');
    const listbox = document.getElementById('orcarouter-model-listbox');
    const wrapper = document.getElementById('orcarouter-model-select-trigger');
    const styles = getComputedStyle(listbox);
    const triggerBox = wrapper.getBoundingClientRect();
    const panelBox = listbox.getBoundingClientRect();
    const transparent = (value) => !value || value === 'transparent'
        || /rgba\\([^)]*,\\s*0(\\.0+)?\\)/.test(value);
    return {
        dropdown_open: !listbox.hidden && trigger.getAttribute('aria-expanded') === 'true',
        item_count: listbox.querySelectorAll('[role="option"]').length,
        opaque_background: !transparent(styles.backgroundColor),
        visible_border: parseFloat(styles.borderTopWidth) > 0
            && !transparent(styles.borderTopColor),
        trigger_panel_right_delta: Math.abs(triggerBox.right - panelBox.right),
        model_ids: Array.from(listbox.querySelectorAll('[role="option"]'))
            .map((option) => option.dataset.modelId)
    };
}"""

AUTH_METRICS = """() => {
    const card = document.getElementById('orcarouter-auth-card');
    const masked = document.getElementById('orcarouter-key-masked');
    const value = (masked.textContent || '').trim();
    const trigger = document.getElementById('orcarouter-model-trigger');
    const refresh = document.getElementById('orcarouter-refresh-btn');
    const method = document.getElementById('orcarouter-auth-method').textContent.trim();
    const env = document.getElementById('orcarouter-key-env').textContent.trim();
    return {
        api_key_visible: method === 'api_key' && value.length > 0
            && !/not configured/i.test(value),
        secret_masked: value.includes('\\u2026') && value.startsWith('sk-orca-'),
        controls_enabled: !trigger.disabled && !refresh.disabled,
        method: method,
        key_env: env,
        card_height: card.getBoundingClientRect().height
    };
}"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _check_screenshot(path: Path) -> None:
    header = path.read_bytes()[:24]
    assert len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", header[16:24])
    assert width >= 800 and height >= 450, f"{path.name} is {width}x{height}"
    assert path.stat().st_size >= 10_000, f"{path.name} is too small"


@pytest.fixture(scope="module")
def dashboard(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Serve the checked-out dashboard on loopback for the duration of the module."""
    if not os.environ.get("ORCAROUTER_API_KEY"):
        pytest.skip("live catalog evidence requires ORCAROUTER_API_KEY")
    if not Path(CHROMIUM).exists():
        pytest.skip("no headless Chromium available")
    pytest.importorskip("playwright.sync_api")

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    home = tmp_path_factory.mktemp("ui-home")
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        # Keep the interpreter's own HOME so the child resolves the same
        # installed packages this test process already imports; the server still
        # runs from `home`, so neither the repository nor a stray .env is used.
        "HOME": os.environ.get("HOME") or str(home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "CI": "1",
        "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "common" / "src"), str(REPO_ROOT / "orchestrator" / "src")]),
        "BUTTERCUP_UI_HOST": "127.0.0.1",
        "BUTTERCUP_UI_PORT": str(port),
        "BUTTERCUP_UI_LOG_LEVEL": "warning",
        "BUTTERCUP_UI_DATABASE_URL": f"sqlite:///{home / 'dashboard.db'}",
        "ORCAROUTER_API_KEY": os.environ["ORCAROUTER_API_KEY"],
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "buttercup.orchestrator.ui.competition_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=home,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise AssertionError("dashboard server exited during startup")
            try:
                with urllib.request.urlopen(base + "/", timeout=2):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise AssertionError("dashboard did not become ready")
        yield base
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


def _payload(base: str, capability: str) -> dict:
    url = f"{base}/v1/providers/orcarouter?capability={capability}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def test_provider_panel_evidence(dashboard: str) -> None:
    """Render the real panel and record the screenshots the PR needs."""
    from playwright.sync_api import sync_playwright

    chat = _payload(dashboard, "chat")
    multimodal = _payload(dashboard, "multimodal")
    assert chat["source"] == "catalog", chat.get("error")
    total = len(chat["models"])
    image = len(multimodal["models"])
    assert image > 0, "catalog advertised no image-input model"
    # The multimodal selector is exactly the chat selector restricted to models
    # whose catalog record declares image input.
    assert [model["id"] for model in multimodal["models"]] == [
        model["id"] for model in chat["models"] if model["multimodal"]
    ]

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(dashboard + "/", wait_until="networkidle")
        page.wait_for_function(
            "() => { const t = document.getElementById('orcarouter-model-trigger');"
            " return t && !t.disabled && t.dataset.selectedModel; }",
            timeout=120_000,
        )

        auth_ui = page.evaluate(AUTH_METRICS)
        assert auth_ui["api_key_visible"], auth_ui
        assert auth_ui["secret_masked"], auth_ui
        assert auth_ui["controls_enabled"], auth_ui
        assert auth_ui["card_height"] > 0, auth_ui
        page.locator("#provider-panel").screenshot(path=str(EVIDENCE_DIR / "auth-methods.png"))
        _check_screenshot(EVIDENCE_DIR / "auth-methods.png")
        artifacts.append(
            {
                "kind": "auth-methods",
                "path": "auth-methods.png",
                "ui": {
                    "api_key_visible": True,
                    "secret_masked": True,
                    "controls_enabled": True,
                    "method": auth_ui["method"],
                    "key_env": auth_ui["key_env"],
                },
            }
        )

        page.click("#orcarouter-model-trigger")
        page.wait_for_selector("#orcarouter-model-listbox:not([hidden])", timeout=15_000)
        text_metrics = page.evaluate(DROPDOWN_METRICS)
        assert text_metrics["dropdown_open"], text_metrics
        assert text_metrics["item_count"] == total, text_metrics
        page.screenshot(path=str(EVIDENCE_DIR / "text-model-dropdown.png"))
        _check_screenshot(EVIDENCE_DIR / "text-model-dropdown.png")
        artifacts.append(
            {
                "kind": "text-model-dropdown",
                "path": "text-model-dropdown.png",
                "ui": {
                    key: text_metrics[key]
                    for key in (
                        "dropdown_open",
                        "item_count",
                        "opaque_background",
                        "visible_border",
                        "trigger_panel_right_delta",
                    )
                },
            }
        )

        page.keyboard.press("Escape")
        page.wait_for_function(
            "() => document.getElementById('orcarouter-model-listbox').hidden === true",
            timeout=15_000,
        )
        page.click('#orcarouter-capabilities [data-capability="multimodal"]')
        page.wait_for_function(
            f"() => document.querySelectorAll('#orcarouter-model-listbox [role=\"option\"]').length === {image}",
            timeout=120_000,
        )
        page.wait_for_function(
            "() => document.getElementById('orcarouter-model-trigger')"
            " && document.getElementById('orcarouter-model-trigger')"
            ".getAttribute('aria-expanded') === 'false'",
            timeout=15_000,
        )
        page.click("#orcarouter-model-trigger")
        page.wait_for_selector("#orcarouter-model-listbox:not([hidden])", timeout=15_000)
        multimodal_metrics = page.evaluate(DROPDOWN_METRICS)
        assert multimodal_metrics["dropdown_open"], multimodal_metrics
        assert multimodal_metrics["item_count"] == image, multimodal_metrics
        page.screenshot(path=str(EVIDENCE_DIR / "multimodal-model-dropdown.png"))
        _check_screenshot(EVIDENCE_DIR / "multimodal-model-dropdown.png")
        artifacts.append(
            {
                "kind": "multimodal-model-dropdown",
                "path": "multimodal-model-dropdown.png",
                "ui": {
                    key: multimodal_metrics[key]
                    for key in (
                        "dropdown_open",
                        "item_count",
                        "opaque_background",
                        "visible_border",
                        "trigger_panel_right_delta",
                    )
                },
            }
        )
        browser.close()

    for item in artifacts:
        item["sha256"] = hashlib.sha256((EVIDENCE_DIR / item["path"]).read_bytes()).hexdigest()
    manifest = {
        "automation": {
            "framework": "playwright",
            "passed": True,
            "catalog_source": CATALOG_URL,
            "catalog_model_count": total,
            "image_model_count": image,
            "base_url": dashboard,
        },
        "artifacts": artifacts,
    }
    (EVIDENCE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
