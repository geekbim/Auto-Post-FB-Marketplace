#!/usr/bin/env python3
"""Automate Facebook Marketplace vehicle form DOM patch.

What it does:
- Opens https://www.facebook.com/marketplace/create/vehicle
- Waits for page/login readiness
- Uploads one photo from this project
- Finds the target <div> by full class signature + empty span text
- Replaces it with wrapped structure and span text "Mobil/Truk"

Usage:
  pip install playwright
  playwright install chromium
  python fb_marketplace_vehicle_dom_update.py

Optional:
  python fb_marketplace_vehicle_dom_update.py --attr-name data-label --attr-value "Mobil/Truk"
  python fb_marketplace_vehicle_dom_update.py --photo-path "Front Page (1).png"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


TARGET_URL = "https://www.facebook.com/marketplace/create/vehicle"
SELLING_URL = "https://www.facebook.com/marketplace/you/selling"
TARGET_TEXT = "Mobil/Truk"
VEHICLE_TYPE_LABEL = "Jenis kendaraan"
VEHICLE_TYPE_WRAPPER_ID = "_r_5u_"
VEHICLE_TYPE_WRAPPER_ID_ALT = "_r_7l_"
VEHICLE_TYPE_WRAPPER_ID_ALT2 = "_r_76_"
VEHICLE_TYPE_WRAPPER_ID_ALT3 = "_r_4p_"
YEAR_FIELD_LABEL = "Tahun"
YEAR_FIELD_WRAPPER_ID = "_r_6b"
YEAR_FIELD_WRAPPER_ID_ALT = "_r_5u_"
TARGET_YEAR_TEXT = "2025"
MAKE_INPUT_ID = "_r_2s_"
MAKE_INPUT_VALUE = "Avanza"
TOYOTA_INPUT_ID = "_r_1s_"
TOYOTA_INPUT_VALUE = "Toyota"
BRAND_LABEL = "Merek"
BRAND_INPUT_ID = "_r_22_"
BRAND_WRAPPER_ID = "_r_6r_"
MODEL_LABEL = "Model"
MODEL_INPUT_ID = "_r_26_"
MODEL_INPUT_ID_ALT = "_r_6a_"
MODEL_INPUT_ID_ALT2 = "_r_76_"
MODEL_INPUT_VALUE = "Avanza"
PRICE_LABEL = "Harga"
PRICE_INPUT_ID = "_r_3a_"
PRICE_INPUT_VALUE = "200000"
MILEAGE_LABEL = "Jarak Tempuh"
MILEAGE_INPUT_ID = "_r_5g_"
MILEAGE_INPUT_ID_ALT = "_r_91_"
MILEAGE_INPUT_VALUE = "120000"
DESCRIPTION_LABEL = "Keterangan"
DESCRIPTION_TEXTAREA_ID = "_r_3e_"
DESCRIPTION_TEXT = "nego tipis km rendah"
LOCATION_LABEL = "Lokasi"
LOCATION_TEXT = "Bekasi"
PHOTO_GLOB_PATTERNS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.heic")
COOKIE_FILE_DEFAULT = "cookies.json"

# Full class signature provided by user.
DIV_CLASS = (
    "xjyslct xjbqb8w x13fuv20 x18b5jzi x1q0q8m5 x1t7ytsu x972fbf x10w94by "
    "x1qhh985 x14e42zd x9f619 xzsf02u x78zum5 x1jchvi3 x1fcty0u x132q4wb "
    "xdj266r x14z9mp xat24cr x1lziwak x1a2a7pz x1a8lsjc xv54qhq xf7dkkf "
    "x9desvi x1n2onr6 x16tdsg8 xh8yej3 x1ja2u2z"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch FB Marketplace vehicle form DOM")
    parser.add_argument(
        "--profile-dir",
        default=".pw-fb-profile",
        help="Playwright persistent profile directory (default: .pw-fb-profile)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless (default: headed)",
    )
    parser.add_argument(
        "--attr-name",
        default="",
        help="Optional attribute name to add to target div",
    )
    parser.add_argument(
        "--attr-value",
        default=TARGET_TEXT,
        help="Attribute value to add to target div",
    )
    parser.add_argument(
        "--photo-path",
        default="",
        help="Optional image path for upload (default: first image found in project root)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=180000,
        help="Max time to wait for patch success in milliseconds",
    )
    parser.add_argument(
        "--data-file",
        default="data.json",
        help="JSON file with one or multiple listing data (default: data.json)",
    )
    parser.add_argument(
        "--cookies-file",
        default=COOKIE_FILE_DEFAULT,
        help="JSON file with Facebook cookies (default: cookies.json)",
    )
    return parser.parse_args()


def _pick_listing_value(listing: dict, keys: tuple[str, ...], fallback: str) -> str:
    for key in keys:
        value = listing.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return fallback


def load_listings_data(data_file: Path) -> list[dict]:
    if not data_file.exists():
        return []
    try:
        payload = json.loads(data_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] invalid data file '{data_file}': {exc}")
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    listings = payload.get("listings")
    if isinstance(listings, list):
        return [item for item in listings if isinstance(item, dict)]

    listing_data = payload.get("listing_data")
    if isinstance(listing_data, list):
        return [item for item in listing_data if isinstance(item, dict)]
    if isinstance(listing_data, dict):
        return [listing_data]

    return []


def load_raw_cookies(cookies_file: Path) -> list[dict]:
    if not cookies_file.exists():
        print(f"[WARN] cookies file not found: {cookies_file}")
        return []
    try:
        payload = json.loads(cookies_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] invalid cookies file '{cookies_file}': {exc}")
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        cookies = payload.get("fb_cookies")
        if isinstance(cookies, list):
            return [item for item in cookies if isinstance(item, dict)]
    return []


def discover_project_photo(project_root: Path) -> Path | None:
    for pattern in PHOTO_GLOB_PATTERNS:
        matches = sorted(project_root.glob(pattern))
        if matches:
            return matches[0]
    return None


def resolve_photo_path(project_root: Path, photo_path_arg: str) -> Path | None:
    if photo_path_arg.strip():
        candidate = Path(photo_path_arg).expanduser()
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        if candidate.exists():
            return candidate
        # Fallback when configured photo path is stale/renamed.
        return discover_project_photo(project_root)
    return discover_project_photo(project_root)


def upload_photo(page, photo_path: Path) -> bool:
    try:
        file_input = page.locator('input[type="file"][accept*="image"]').first
        if file_input.count() > 0:
            file_input.set_input_files(str(photo_path))
        else:
            add_btn = page.get_by_role("button", name=re.compile("Tambahkan Foto|Tambahkan foto", re.I)).first
            if add_btn.count() == 0:
                return False
            with page.expect_file_chooser(timeout=4000) as chooser_info:
                add_btn.click()
            chooser_info.value.set_files(str(photo_path))

        page.locator('[aria-label="Hapus foto dari tawaran"]').first.wait_for(timeout=12000)
        print(f"[OK] Photo uploaded: {photo_path}")
        return True
    except Exception as exc:
        print(f"[WARN] photo upload retry: {exc}")
        return False


def click_save_draft(page) -> bool:
    try:
        role_btn = page.get_by_role("button", name=re.compile("Simpan draf", re.I)).first
        if role_btn.count() > 0:
            role_btn.click(timeout=3000)
            print("[OK] Clicked Simpan draf")
            return True

        container = page.locator('div[role="none"]').filter(has_text=re.compile("Simpan draf", re.I)).first
        if container.count() > 0:
            container.click(timeout=3000, force=True)
            print("[OK] Clicked Simpan draf")
            return True

        text_node = page.locator("span").filter(has_text=re.compile("^\\s*Simpan draf\\s*$", re.I)).first
        if text_node.count() > 0:
            clickable = text_node.locator("xpath=ancestor::div[@role='none'][1]")
            if clickable.count() > 0:
                clickable.click(timeout=3000, force=True)
                print("[OK] Clicked Simpan draf")
                return True

        return False
    except Exception as exc:
        print(f"[WARN] save draft retry: {exc}")
        return False


def click_tinggalkan_halaman(page) -> bool:
    try:
        def leave_confirmation_present() -> bool:
            try:
                return bool(
                    page.evaluate(
                        """
                        () => {
                          const isVisible = (el) => {
                            if (!el) return false;
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                          };
                          const candidates = Array.from(document.querySelectorAll('[role="button"], div[role="none"], span'))
                            .filter((el) => (el.getAttribute?.('aria-label') || '').toLowerCase().includes('tinggalkan halaman')
                              || (el.textContent || '').toLowerCase().includes('tinggalkan halaman'));
                          return candidates.some(isVisible);
                        }
                        """
                    )
                )
            except Exception:
                return False

        def click_first_actionable(locator) -> bool:
            count = locator.count()
            for i in range(count):
                item = locator.nth(i)
                try:
                    item.click(timeout=1000, trial=True)
                    item.click(timeout=2000)
                    return True
                except Exception:
                    continue
            return False

        deadline = time.time() + 10
        while time.time() < deadline:
            selectors = [
                '[role="dialog"] [role="button"][aria-label="Tinggalkan Halaman"]:visible:not([aria-disabled="true"])',
                '[role="button"][aria-label="Tinggalkan Halaman"]:visible:not([aria-disabled="true"])',
                '[role="button"]:visible:not([aria-disabled="true"]):has-text("Tinggalkan Halaman")',
                '[role="dialog"] [role="none"]:visible:has-text("Tinggalkan Halaman")',
                'div[role="none"]:visible:has-text("Tinggalkan Halaman")',
            ]
            for selector in selectors:
                if click_first_actionable(page.locator(selector)):
                    print("[OK] Clicked Tinggalkan Halaman")
                    return True

            # JS fallback for dynamic overlays where Playwright visibility checks are flaky.
            js_clicked = page.evaluate(
                """
                () => {
                  const isVisible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                  };
                  const matches = Array.from(document.querySelectorAll('[role="button"], div[role="none"]'))
                    .filter((el) => (el.getAttribute('aria-label') || '').toLowerCase().includes('tinggalkan halaman')
                      || (el.textContent || '').toLowerCase().includes('tinggalkan halaman'));
                  const target = matches.find((el) => isVisible(el) && el.getAttribute('aria-disabled') !== 'true');
                  if (!target) return false;
                  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                  return true;
                }
                """
            )
            if js_clicked:
                print("[OK] Clicked Tinggalkan Halaman")
                return True

            page.wait_for_timeout(350)

        # If no leave confirmation is shown, treat it as already resolved.
        if not leave_confirmation_present():
            print("[OK] Tinggalkan Halaman not required")
            return True
        return False
    except Exception as exc:
        print(f"[WARN] leave-page retry: {exc}")
        return False


def get_combobox_display_value(page, label_text: str) -> str:
    script = """
    ({ labelText }) => {
      const combos = Array.from(document.querySelectorAll('label[role="combobox"], div[role="combobox"]'));
      for (const combo of combos) {
        const labels = Array.from(combo.querySelectorAll('span'));
        const hasLabel = labels.some((s) => (s.textContent || '').trim() === labelText);
        if (!hasLabel) continue;
        const valueSpan = combo.querySelector('div.xh8yej3[tabindex="-1"] span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
        if (valueSpan) {
          return (valueSpan.textContent || '').replace(/\\u00a0/g, '').trim();
        }
        const textInput = combo.querySelector('input[type="text"], input[role="combobox"], textarea');
        if (textInput) {
          const raw = (textInput.value || textInput.getAttribute('value') || '').toString();
          return raw.replace(/\\u00a0/g, '').trim();
        }
      }
      return '';
    }
    """
    try:
        return page.evaluate(script, {"labelText": label_text}) or ""
    except Exception:
        return ""


def select_combobox_option(page, label_text: str, option_text: str) -> bool:
    combo = page.locator('label[role="combobox"], div[role="combobox"]').filter(
        has_text=re.compile(re.escape(label_text), re.I)
    ).first
    if combo.count() == 0:
        # Not a combobox on this variant; skip strict enforcement here.
        return True

    try:
        combo.click(timeout=2500)
    except Exception:
        try:
            combo.click(timeout=2500, force=True)
        except Exception:
            return False

    page.wait_for_timeout(250)

    # If this combobox has an editable input, type + Enter to trigger real selection state.
    editable = combo.locator('input[type="text"], input[role="combobox"], textarea').first
    if editable.count() > 0:
        try:
            editable.click(timeout=1200)
            try:
                editable.fill(option_text, timeout=1800)
            except Exception:
                # Some FB controls reject fill(); fallback to Ctrl/Meta+A + type.
                editable.press("ControlOrMeta+a", timeout=800)
                editable.type(option_text, delay=20, timeout=2200)
            editable.press("Enter", timeout=1200)
            page.wait_for_timeout(300)
        except Exception:
            pass

    option_patterns = [
        page.get_by_role("option", name=option_text, exact=True).first,
        page.locator('[role="option"]').filter(has_text=option_text).first,
        page.locator('[role="listbox"] span').filter(has_text=option_text).first,
        page.locator('[role="option"]').filter(has_text=re.compile(re.escape(option_text), re.I)).first,
        page.locator('[role="listbox"] span').filter(has_text=re.compile(re.escape(option_text), re.I)).first,
    ]

    clicked = False
    for opt in option_patterns:
        if opt.count() == 0:
            continue
        try:
            opt.click(timeout=1200, trial=True)
            opt.click(timeout=2500)
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        # A visible combobox must fire a real selection event to persist in FB state.
        return False

    page.wait_for_timeout(250)
    final_value = get_combobox_display_value(page, label_text)
    return final_value == option_text or option_text.lower() in final_value.lower()


def enforce_select_fields(page, select_fields: tuple[tuple[str, str], ...]) -> bool:
    ok = True
    for label_text, option_text in select_fields:
        field_ok = select_combobox_option(page, label_text, option_text)
        if not field_ok:
            print(f"[WARN] select field not persisted: label={label_text} value={option_text}")
        ok = ok and field_ok
    return ok


def enforce_model_input_commit(page, label_text: str, model_value: str) -> bool:
    containers = page.locator("div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6").filter(
        has_text=re.compile(rf"^\\s*{re.escape(label_text)}\\s*$", re.I)
    )
    if containers.count() == 0:
        containers = page.locator("div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6").filter(
            has_text=re.compile(re.escape(label_text), re.I)
        )
    if containers.count() == 0:
        return True

    visible_containers = containers.locator(":scope:visible")
    active_containers = visible_containers if visible_containers.count() > 0 else containers

    def norm(v: str) -> str:
        return re.sub(r"\s+", " ", (v or "")).strip().lower()

    def read_visible_model_value() -> str:
        script = """
        ({ labelText }) => {
          const isVisible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          };
          const groups = Array.from(document.querySelectorAll('div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6'));
          for (const g of groups) {
            if (!isVisible(g)) continue;
            const labels = Array.from(g.querySelectorAll('span'));
            const hasLabel = labels.some((s) => (s.textContent || '').trim() === labelText);
            if (!hasLabel) continue;

            const input = g.querySelector('input[type="text"]');
            if (input && isVisible(input)) {
              return (input.value || input.getAttribute('value') || '').toString().trim();
            }

            const wrapped = g.querySelector('div.xh8yej3[tabindex="-1"] span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
            if (wrapped && isVisible(wrapped)) {
              return (wrapped.textContent || '').replace(/\\u00a0/g, '').trim();
            }
          }
          return '';
        }
        """
        try:
            return page.evaluate(script, {"labelText": label_text}) or ""
        except Exception:
            return ""

    required = False
    for i in range(active_containers.count()):
        container = active_containers.nth(i)
        model_input = container.locator('input[type="text"]:visible').first
        if model_input.count() == 0:
            model_input = container.locator('input[type="text"]').first
        if model_input.count() == 0:
            continue

        required = True
        try:
            model_input.scroll_into_view_if_needed(timeout=1200)
            model_input.click(timeout=1200)
            model_input.press("ControlOrMeta+a", timeout=800)
            model_input.type(model_value, delay=30, timeout=2500)
            page.wait_for_timeout(180)

            # Force exact plain-text value via native setter + React events.
            handle = model_input.element_handle()
            if handle is not None:
                page.evaluate(
                    """
                    ({ el, value }) => {
                      if (!el) return;
                      const setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype,
                        'value'
                      )?.set;
                      if (setter) setter.call(el, value);
                      else el.value = value;
                      el.setAttribute('value', value);
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      el.blur();
                    }
                    """,
                    {"el": handle, "value": model_value},
                )
            else:
                model_input.press("ControlOrMeta+a", timeout=800)
                model_input.type(model_value, delay=30, timeout=2500)

            # Commit focus-out without selecting dropdown options (can map to numeric IDs).
            try:
                model_input.press("Tab", timeout=1200)
            except Exception:
                pass
            page.wait_for_timeout(420)

            current = model_input.input_value().strip()
            visible_value = read_visible_model_value().strip()
            current_ok = norm(current) == norm(model_value) and not current.isdigit()
            visible_ok = norm(visible_value) == norm(model_value) and not visible_value.isdigit()
            if current_ok and visible_ok:
                return True

            # Fallback: enforce plain text model and fire React-relevant events.
            if current.isdigit() or visible_value.isdigit():
                model_input.click(timeout=1200)
                model_input.press("ControlOrMeta+a", timeout=800)
                model_input.type(model_value, delay=25, timeout=2200)
                page.evaluate(
                    """
                    (el) => {
                      if (!el) return;
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                    """,
                    model_input.element_handle(),
                )
                page.wait_for_timeout(350)
                current2 = model_input.input_value().strip()
                visible2 = read_visible_model_value().strip()
                if norm(current2) == norm(model_value) and norm(visible2) == norm(model_value):
                    return True
        except Exception:
            continue

    return not required


def enforce_labeled_text_input_commit(
    page, label_text: str, target_value: str, digits_only: bool = False
) -> bool:
    containers = page.locator("div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6").filter(
        has_text=re.compile(re.escape(label_text), re.I)
    )
    if containers.count() == 0:
        return True

    visible_containers = containers.locator(":scope:visible")
    active_containers = visible_containers if visible_containers.count() > 0 else containers

    required = False
    expected_digits = re.sub(r"\D+", "", target_value or "")

    for i in range(active_containers.count()):
        container = active_containers.nth(i)
        input_el = container.locator('input[type="text"]:visible').first
        if input_el.count() == 0:
            input_el = container.locator('input[type="text"]').first
        if input_el.count() == 0:
            continue

        required = True
        try:
            input_el.scroll_into_view_if_needed(timeout=1200)
            input_el.click(timeout=1200)
            input_el.press("ControlOrMeta+a", timeout=800)
            input_el.type(target_value, delay=25, timeout=2200)

            handle = input_el.element_handle()
            if handle is not None:
                page.evaluate(
                    """
                    ({ el, value }) => {
                      if (!el) return;
                      const setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype,
                        'value'
                      )?.set;
                      if (setter) setter.call(el, value);
                      else el.value = value;
                      el.setAttribute('value', value);
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                      el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                    """,
                    {"el": handle, "value": target_value},
                )

            try:
                input_el.press("Tab", timeout=1000)
            except Exception:
                pass
            page.wait_for_timeout(350)

            current = (input_el.input_value() or "").strip()
            if digits_only:
                current_digits = re.sub(r"\D+", "", current)
                if expected_digits and current_digits == expected_digits:
                    return True
            elif re.sub(r"\s+", " ", current).strip().lower() == re.sub(
                r"\s+", " ", target_value
            ).strip().lower():
                return True
        except Exception:
            continue

    return not required


def wait_and_find_berikutnya(page, timeout_ms: int = 4000) -> dict:
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        info = page.evaluate(
            """
            () => {
              const nodes = Array.from(document.querySelectorAll('[role="button"][aria-label="Berikutnya"], [role="button"]'))
                .filter((el) => {
                  const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                  const txt = (el.textContent || '').trim().toLowerCase();
                  return aria === 'berikutnya' || txt.includes('berikutnya');
                });
              const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              const actionable = nodes.filter((el) => isVisible(el) && el.getAttribute('aria-disabled') !== 'true' && el.getAttribute('tabindex') !== '-1');
              return {
                total: nodes.length,
                visible: nodes.filter(isVisible).length,
                actionable: actionable.length,
                sample: nodes.slice(0, 3).map((el) => ({
                  ariaLabel: el.getAttribute('aria-label'),
                  ariaDisabled: el.getAttribute('aria-disabled'),
                  tabindex: el.getAttribute('tabindex'),
                  className: (el.className || '').toString().slice(0, 160),
                  text: (el.textContent || '').trim().slice(0, 40),
                })),
              };
            }
            """
        )
        if info.get("actionable", 0) > 0:
            return {"found": True, **info}
        page.wait_for_timeout(250)
    return {"found": False, "url": page.url, **page.evaluate(
        """
        () => {
          const nodes = Array.from(document.querySelectorAll('[role="button"][aria-label="Berikutnya"], [role="button"]'))
            .filter((el) => {
              const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
              const txt = (el.textContent || '').trim().toLowerCase();
              return aria === 'berikutnya' || txt.includes('berikutnya');
            });
          const isVisible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          return {
            total: nodes.length,
            visible: nodes.filter(isVisible).length,
            actionable: nodes.filter((el) => isVisible(el) && el.getAttribute('aria-disabled') !== 'true' && el.getAttribute('tabindex') !== '-1').length,
            sample: nodes.slice(0, 3).map((el) => ({
              ariaLabel: el.getAttribute('aria-label'),
              ariaDisabled: el.getAttribute('aria-disabled'),
              tabindex: el.getAttribute('tabindex'),
              className: (el.className || '').toString().slice(0, 160),
              text: (el.textContent || '').trim().slice(0, 40),
            })),
          };
        }
        """
    )}


def normalize_cookies(raw_cookies: list[dict]) -> list[dict]:
    same_site_map = {
        "lax": "Lax",
        "strict": "Strict",
        "no_restriction": "None",
        "none": "None",
    }
    normalized = []
    for c in raw_cookies:
        item = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
        }
        same_site = c.get("sameSite")
        if same_site is not None:
            mapped = same_site_map.get(str(same_site).lower())
            if mapped:
                item["sameSite"] = mapped

        if not c.get("session", False) and c.get("expirationDate") is not None:
            item["expires"] = float(c["expirationDate"])

        normalized.append(item)
    return normalized


def patch_dom(page, attr_name: str, attr_value: str) -> bool:
    script = """
    ({ divClass, targetText, vehicleTypeLabel, vehicleTypeWrapperId, vehicleTypeWrapperIdAlt, vehicleTypeWrapperIdAlt2, vehicleTypeWrapperIdAlt3, yearFieldLabel, yearFieldWrapperId, yearFieldWrapperIdAlt, targetYearText, makeInputId, makeInputValue, toyotaInputId, toyotaInputValue, brandLabel, brandInputId, brandWrapperId, modelLabel, modelInputId, modelInputIdAlt, modelInputIdAlt2, modelInputValue, priceLabel, priceInputId, priceInputValue, mileageLabel, mileageInputId, mileageInputIdAlt, mileageInputValue, descriptionLabel, descriptionTextareaId, descriptionText, attrName, attrValue, locationLabel, locationText }) => {
      const normalize = (v) => {
        if (v == null) return '';
        if (typeof v === 'string') return v.replace(/\s+/g, " ").trim();
        if (typeof v === 'object') {
          if (typeof v.baseVal === 'string') return v.baseVal.replace(/\s+/g, " ").trim();
          if (typeof v.value === 'string') return v.value.replace(/\s+/g, " ").trim();
        }
        return String(v).replace(/\s+/g, " ").trim();
      };
      const classNeedle = normalize(divClass);
      const labelTexts = [
        vehicleTypeLabel,
        yearFieldLabel,
        brandLabel,
        modelLabel,
        priceLabel,
        descriptionLabel,
        locationLabel,
      ];
      const allSpans = Array.from(document.querySelectorAll('span'));
      const pageReady = labelTexts.some((labelText) =>
        allSpans.some((s) => (s.textContent || '').trim() === labelText)
      );
      if (!pageReady) {
        return {
          ok: false,
          pageReady: false,
          url: window.location.href,
          title: document.title || '',
        };
      }

      let vehiclePatched = false;
      let yearPatched = false;
      let secondYearPatched = false;
      let thirdYearPatched = false;
      let makePatched = false;
      let toyotaInputPatched = false;
      let vehicleTypePatched = false;
      let yearFieldPatched = false;
      let modelPatched = false;
      let pricePatched = false;
      let mileagePatched = false;
      let descriptionPatched = false;
      let makeRequired = false;
      let toyotaInputRequired = false;
      let vehicleTypeRequired = false;
      let yearFieldRequired = false;
      let modelRequired = false;
      let priceRequired = false;
      let mileageRequired = false;
      let descriptionRequired = false;
      let locationPatched = false;
      let vehicleWrapperHTML = '';
      let vehicleOuterHTML = '';
      let yearWrapperHTML = '';
      let yearOuterHTML = '';
      let secondYearWrapperHTML = '';
      let secondYearOuterHTML = '';
      let thirdYearWrapperHTML = '';
      let thirdYearOuterHTML = '';
      let makeOuterHTML = '';
      let toyotaInputHTML = '';
      let vehicleTypeHTML = '';
      let yearFieldHTML = '';
      let modelHTML = '';
      let priceHTML = '';
      let mileageHTML = '';
      let descriptionHTML = '';
      let locationOuterHTML = '';
      const usedYearWrappers = new Set();
      const asText = (v) => (v == null ? '' : String(v));
      const isVisible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      };

      const readControlValue = (el) => {
        if (!el) return '';
        if (typeof el.value === 'string') return el.value;
        const attrVal = el.getAttribute ? el.getAttribute('value') : '';
        return attrVal || '';
      };

      const digitsOnly = (v) => asText(v).replace(/\D+/g, '');
      const normalizedText = (v) => asText(v).replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
      const modelTextMatches = (v) => {
        const cleaned = asText(v).replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
        if (!cleaned || /^\d+$/.test(cleaned)) return false;
        return normalizedText(cleaned) === normalizedText(modelInputValue);
      };

      const setControlValue = (el, value, validator = null) => {
        if (!el) return false;
        const textValue = asText(value);
        const tag = (el.tagName || '').toLowerCase();
        let setter = null;

        if (tag === 'textarea') {
          setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set || null;
        } else if (tag === 'input') {
          setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set || null;
        }

        if (setter) {
          setter.call(el, textValue);
        } else {
          el.value = textValue;
        }
        if (tag === 'textarea') {
          el.textContent = textValue;
        }
        if (el.setAttribute) {
          el.setAttribute('value', textValue);
        }

        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        const actual = readControlValue(el);
        if (typeof validator === 'function') {
          return !!validator(actual, textValue);
        }
        return actual === textValue;
      };

      const patchExistingWrapper = (wrapper, textValue, forceId = '') => {
        if (!wrapper || normalize(wrapper.className) !== 'xh8yej3') return { ok: false };
        const inner = wrapper.firstElementChild;
        if (!inner) return { ok: false };
        const span = inner.querySelector('span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
        if (!span) return { ok: false };

        span.textContent = textValue;
        wrapper.className = 'xh8yej3';
        if (forceId) {
          wrapper.id = forceId;
        }
        wrapper.setAttribute('tabindex', '-1');
        return { ok: true, wrapperHTML: wrapper.outerHTML, outerHTML: inner.outerHTML };
      };

      const findFallbackYearWrapper = () => {
        const wrappers = Array.from(document.querySelectorAll('div.xh8yej3[tabindex="-1"]'));
        for (const wrapper of wrappers) {
          if (usedYearWrappers.has(wrapper)) continue;
          if (wrapper.id === '_r_25_') continue;

          const inner = wrapper.firstElementChild;
          if (!inner) continue;
          const span = inner.querySelector('span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
          if (!span) continue;
          const current = (span.textContent || "").replace(/\u00a0/g, "").trim();
          if (current !== '' && current !== targetYearText) continue;
          return wrapper;
        }
        return null;
      };

      const setWrappedTargetText = (wrapperId, textValue, allowWrapCreate) => {
        const directWrapper = document.getElementById(wrapperId);
        if (directWrapper) {
          const patched = patchExistingWrapper(directWrapper, textValue, wrapperId);
          if (patched.ok) {
            if (attrName && wrapperId === '_r_25_') {
              const inner = directWrapper.firstElementChild;
              if (inner) inner.setAttribute(attrName, attrValue);
            }
            return patched;
          }
        }

        if (!allowWrapCreate) {
          return { ok: false };
        }

        const candidates = Array.from(document.querySelectorAll('div'))
          .filter((d) => normalize(d.className) === classNeedle);
        for (const div of candidates) {
          const span = div.querySelector('span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
          if (!span) continue;
          const current = (span.textContent || "").replace(/\u00a0/g, "").trim();
          if (current !== "") continue;

          span.textContent = textValue;
          if (attrName && wrapperId === '_r_25_') {
            div.setAttribute(attrName, attrValue);
          }

          const newWrapper = document.createElement('div');
          newWrapper.className = 'xh8yej3';
          newWrapper.id = wrapperId;
          newWrapper.setAttribute('tabindex', '-1');
          div.replaceWith(newWrapper);
          newWrapper.appendChild(div);
          return { ok: true, wrapperHTML: newWrapper.outerHTML, outerHTML: div.outerHTML };
        }
        return { ok: false };
      };

      const vehicleResult = setWrappedTargetText('_r_25_', targetText, true);
      if (vehicleResult.ok) {
        vehiclePatched = true;
        vehicleWrapperHTML = vehicleResult.wrapperHTML || '';
        vehicleOuterHTML = vehicleResult.outerHTML || '';
      }

      const vehicleTypeContainers = Array.from(document.querySelectorAll('div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6'))
        .filter((container) => {
          const labels = Array.from(container.querySelectorAll('span'));
          return labels.some((label) => (label.textContent || '').trim() === vehicleTypeLabel);
        });
      if (vehicleTypeContainers.length > 0) {
        vehicleTypeRequired = true;
        const orderedVehicleTypeContainers = [
          ...vehicleTypeContainers.filter(isVisible),
          ...vehicleTypeContainers.filter((c) => !isVisible(c)),
        ];
        for (const container of orderedVehicleTypeContainers) {
          let result = { ok: false };
          const wrappers = [
            container.querySelector(`#${vehicleTypeWrapperId}`),
            container.querySelector(`#${vehicleTypeWrapperIdAlt}`),
            container.querySelector(`#${vehicleTypeWrapperIdAlt2}`),
            container.querySelector(`#${vehicleTypeWrapperIdAlt3}`),
            container.querySelector('div.xh8yej3[tabindex="-1"]'),
          ].filter(Boolean);

          for (const wrapper of wrappers) {
            result = patchExistingWrapper(wrapper, targetText);
            if (result.ok) break;
          }
          if (!result.ok) {
            result = setWrappedTargetText(vehicleTypeWrapperId, targetText, false);
          }
          if (!result.ok) {
            result = setWrappedTargetText(vehicleTypeWrapperIdAlt, targetText, false);
          }
          if (!result.ok) {
            result = setWrappedTargetText(vehicleTypeWrapperIdAlt2, targetText, false);
          }
          if (!result.ok) {
            result = setWrappedTargetText(vehicleTypeWrapperIdAlt3, targetText, false);
          }
          if (result.ok) {
            vehicleTypePatched = true;
            vehicleTypeHTML = result.wrapperHTML || result.outerHTML || container.outerHTML;
            break;
          }
        }
      }

      const yearComboboxBlocks = Array.from(document.querySelectorAll('label[role="combobox"], div[role="combobox"]'))
        .filter((combo) => {
          const labels = Array.from(combo.querySelectorAll('span'));
          return labels.some((label) => (label.textContent || '').trim() === yearFieldLabel);
        });
      if (yearComboboxBlocks.length > 0) {
        yearFieldRequired = true;
        const orderedYearComboboxBlocks = [
          ...yearComboboxBlocks.filter(isVisible),
          ...yearComboboxBlocks.filter((c) => !isVisible(c)),
        ];
        for (const combo of orderedYearComboboxBlocks) {
          let yearFieldResult = { ok: false };
          const wrappers = [
            combo.querySelector(`#${yearFieldWrapperId}`),
            combo.querySelector(`#${yearFieldWrapperIdAlt}`),
            ...Array.from(combo.querySelectorAll('div.xh8yej3[tabindex="-1"]')),
          ].filter(Boolean);
          for (const wrapper of wrappers) {
            yearFieldResult = patchExistingWrapper(
              wrapper,
              targetYearText,
              wrapper.id || "",
            );
            if (yearFieldResult.ok) break;
          }
          if (!yearFieldResult.ok) {
            yearFieldResult = setWrappedTargetText(yearFieldWrapperId, targetYearText, false);
          }
          if (!yearFieldResult.ok) {
            yearFieldResult = setWrappedTargetText(yearFieldWrapperIdAlt, targetYearText, false);
          }
          if (yearFieldResult.ok) {
            yearFieldPatched = true;
            yearFieldHTML = yearFieldResult.wrapperHTML || yearFieldResult.outerHTML || combo.outerHTML;
            break;
          }
        }
      }

      const yearResult = setWrappedTargetText('_r_2k_', targetYearText, false);
      if (yearResult.ok) {
        const directYearWrapper = document.getElementById('_r_2k_');
        if (directYearWrapper) usedYearWrappers.add(directYearWrapper);
      }
      let finalYearResult = yearResult;
      if (!finalYearResult.ok) {
        const fallback = findFallbackYearWrapper();
        if (fallback) {
          usedYearWrappers.add(fallback);
          finalYearResult = patchExistingWrapper(fallback, targetYearText);
        }
      }
      if (finalYearResult.ok) {
        yearPatched = true;
        yearWrapperHTML = finalYearResult.wrapperHTML || '';
        yearOuterHTML = finalYearResult.outerHTML || '';
      }

      const secondYearResult = setWrappedTargetText('_r_2c_', targetYearText, false);
      if (secondYearResult.ok) {
        const directSecondYearWrapper = document.getElementById('_r_2c_');
        if (directSecondYearWrapper) usedYearWrappers.add(directSecondYearWrapper);
      }
      let finalSecondYearResult = secondYearResult;
      if (!finalSecondYearResult.ok) {
        const fallback = findFallbackYearWrapper();
        if (fallback) {
          usedYearWrappers.add(fallback);
          finalSecondYearResult = patchExistingWrapper(fallback, targetYearText);
        }
      }
      if (finalSecondYearResult.ok) {
        secondYearPatched = true;
        secondYearWrapperHTML = finalSecondYearResult.wrapperHTML || '';
        secondYearOuterHTML = finalSecondYearResult.outerHTML || '';
      }

      const thirdYearResult = setWrappedTargetText('_r_2v_', targetYearText, false);
      if (thirdYearResult.ok) {
        const directThirdYearWrapper = document.getElementById('_r_2v_');
        if (directThirdYearWrapper) usedYearWrappers.add(directThirdYearWrapper);
      }
      let finalThirdYearResult = thirdYearResult;
      if (!finalThirdYearResult.ok) {
        const fallback = findFallbackYearWrapper();
        if (fallback) {
          usedYearWrappers.add(fallback);
          finalThirdYearResult = patchExistingWrapper(fallback, targetYearText);
        }
      }
      if (finalThirdYearResult.ok) {
        thirdYearPatched = true;
        thirdYearWrapperHTML = finalThirdYearResult.wrapperHTML || '';
        thirdYearOuterHTML = finalThirdYearResult.outerHTML || '';
      }

      const makeInput = document.getElementById(makeInputId);
      if (makeInput && makeInput.tagName.toLowerCase() === 'input') {
        makeRequired = true;
        makePatched = setControlValue(makeInput, makeInputValue);
        makeOuterHTML = makeInput.outerHTML;
      } else {
        const existingMakeDiv = Array.from(document.querySelectorAll('div'))
          .find((d) => {
            if (normalize(d.className) !== classNeedle) return false;
            const span = d.querySelector('span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
            if (!span) return false;
            return (span.textContent || '').trim() === toyotaInputValue;
          });
        if (existingMakeDiv) {
          makeRequired = true;
          const recoveredInput = document.createElement('input');
          recoveredInput.className = 'x1i10hfl xggy1nq xtpw4lu x1tutvks x1s3xk63 x1s07b3s x1kdt53j x1a2a7pz xjbqb8w x1ejq31n x18oe1m7 x1sy0etr xstzfhl x9f619 xzsf02u x1uxerd5 x1fcty0u x132q4wb x1a8lsjc xv54qhq xf7dkkf x9desvi xh8yej3';
          recoveredInput.setAttribute('dir', 'ltr');
          recoveredInput.id = makeInputId;
          recoveredInput.type = 'text';
          setControlValue(recoveredInput, makeInputValue);
          existingMakeDiv.replaceWith(recoveredInput);
          makePatched = readControlValue(recoveredInput) === asText(makeInputValue);
          makeOuterHTML = recoveredInput.outerHTML;
        } else {
          const existingMakeInput = document.getElementById(makeInputId);
          if (existingMakeInput) {
            makeRequired = true;
            makePatched = readControlValue(existingMakeInput) === asText(makeInputValue);
            makeOuterHTML = existingMakeInput.outerHTML;
          }
        }
      }

      const toyotaInput = document.getElementById(toyotaInputId);
      const brandContainers = Array.from(document.querySelectorAll('div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6'));
      const matchingBrandContainers = brandContainers.filter((container) => {
        const label = container.querySelector('span');
        return label && (label.textContent || '').trim() === brandLabel;
      });
      if (matchingBrandContainers.length > 0) {
        toyotaInputRequired = true;
        // Prefer visible containers/inputs first to avoid hidden React clones.
        const orderedContainers = [
          ...matchingBrandContainers.filter(isVisible),
          ...matchingBrandContainers.filter((c) => !isVisible(c)),
        ];
        for (const container of orderedContainers) {
          // First, handle select/combobox-style brand fields.
          const wrapperCandidates = [
            container.querySelector(`#${brandWrapperId}`),
            ...Array.from(container.querySelectorAll('div.xh8yej3[tabindex="-1"]')),
          ].filter(Boolean);
          for (const wrapper of wrapperCandidates) {
            const wrapperResult = patchExistingWrapper(wrapper, toyotaInputValue, wrapper.id || "");
            if (wrapperResult.ok) {
              toyotaInputPatched = true;
              toyotaInputHTML = wrapperResult.wrapperHTML || wrapperResult.outerHTML || container.outerHTML;
              break;
            }
          }
          if (toyotaInputPatched) break;

          // Fallback to text-input brand fields.
          const inputCandidates = [
            ...Array.from(container.querySelectorAll(`input#${brandInputId}`)),
            ...Array.from(container.querySelectorAll('input[type="text"]')),
          ];
          const orderedInputs = [
            ...inputCandidates.filter(isVisible),
            ...inputCandidates.filter((i) => !isVisible(i)),
          ];
          for (const inputEl of orderedInputs) {
            if ((inputEl.tagName || '').toLowerCase() !== 'input') continue;
            const ok = setControlValue(inputEl, toyotaInputValue);
            if (ok) {
              toyotaInputPatched = true;
              toyotaInputHTML = container.outerHTML;
              break;
            }
          }
          if (toyotaInputPatched) break;
        }
      } else if (toyotaInput && toyotaInput.tagName.toLowerCase() === 'input') {
        toyotaInputRequired = true;
        toyotaInputPatched = setControlValue(toyotaInput, toyotaInputValue);
        toyotaInputHTML = toyotaInput.outerHTML;
      } else {
        const existingToyotaInput = document.getElementById(toyotaInputId);
        if (existingToyotaInput) {
          toyotaInputRequired = true;
          toyotaInputPatched = readControlValue(existingToyotaInput) === asText(toyotaInputValue);
          toyotaInputHTML = existingToyotaInput.outerHTML;
        }
      }

      const matchingModelContainers = brandContainers.filter((container) => {
        const label = container.querySelector('span');
        return label && (label.textContent || '').trim() === modelLabel;
      });
      if (matchingModelContainers.length > 0) {
        modelRequired = true;
        const orderedModelContainers = [
          ...matchingModelContainers.filter(isVisible),
          ...matchingModelContainers.filter((c) => !isVisible(c)),
        ];
        for (const container of orderedModelContainers) {
          // Read-only check here: real model commit is handled by Python flow.
          const wrapperCandidates = Array.from(container.querySelectorAll('div.xh8yej3[tabindex="-1"]'));
          for (const wrapper of wrapperCandidates) {
            const valueSpan = wrapper.querySelector('span.x6ikm8r.x10wlt62.xlyipyv.xuxw1ft');
            if (valueSpan && modelTextMatches(valueSpan.textContent || '')) {
              modelPatched = true;
              modelHTML = container.outerHTML;
              break;
            }
          }
          if (modelPatched) break;

          // Check text-input model fields without mutating them here.
          const inputCandidates = [
            ...Array.from(container.querySelectorAll(`input#${modelInputId}`)),
            ...Array.from(container.querySelectorAll(`input#${modelInputIdAlt}`)),
            ...Array.from(container.querySelectorAll(`input#${modelInputIdAlt2}`)),
            ...Array.from(container.querySelectorAll('input[type="text"]')),
          ];
          const orderedInputs = [
            ...inputCandidates.filter(isVisible),
            ...inputCandidates.filter((i) => !isVisible(i)),
          ];
          for (const inputEl of orderedInputs) {
            if ((inputEl.tagName || '').toLowerCase() !== 'input') continue;
            const currentValue = readControlValue(inputEl);
            if (modelTextMatches(currentValue)) {
              modelPatched = true;
              modelHTML = container.outerHTML;
              break;
            }
          }
          if (modelPatched) break;
        }
      } else {
        const fallbackModelInput = document.querySelector(`input#${modelInputId}`);
        const fallbackModelInputAlt = document.querySelector(`input#${modelInputIdAlt}`);
        const fallbackModelInputAlt2 = document.querySelector(`input#${modelInputIdAlt2}`);
        const modelFallback = fallbackModelInput || fallbackModelInputAlt || fallbackModelInputAlt2;
        if (modelFallback) {
          modelRequired = true;
          modelPatched = modelTextMatches(readControlValue(modelFallback));
          modelHTML = modelFallback.outerHTML;
        }
      }

      const priceContainer = brandContainers.find((container) => {
        const label = container.querySelector('span');
        return label && (label.textContent || '').trim() === priceLabel;
      });
      let priceInput = null;
      if (priceContainer) {
        priceInput = priceContainer.querySelector(`input#${priceInputId}`) || priceContainer.querySelector('input[type="text"]');
      }
      if (priceInput && priceInput.tagName.toLowerCase() === 'input') {
        priceRequired = true;
        pricePatched = setControlValue(
          priceInput,
          priceInputValue,
          (actual, expected) => {
            const expectedDigits = digitsOnly(expected);
            if (!expectedDigits) return asText(actual).trim() === asText(expected).trim();
            return digitsOnly(actual) === expectedDigits;
          },
        );
        priceHTML = priceContainer.outerHTML;
      } else {
        const fallbackPriceInput = document.querySelector(`input#${priceInputId}`);
        if (fallbackPriceInput) {
          priceRequired = true;
          pricePatched = setControlValue(
            fallbackPriceInput,
            priceInputValue,
            (actual, expected) => {
              const expectedDigits = digitsOnly(expected);
              if (!expectedDigits) return asText(actual).trim() === asText(expected).trim();
              return digitsOnly(actual) === expectedDigits;
            },
          );
          priceHTML = fallbackPriceInput.outerHTML;
        }
      }

      const mileageContainer = brandContainers.find((container) => {
        const labels = Array.from(container.querySelectorAll('span'));
        return labels.some((label) => (label.textContent || '').trim() === mileageLabel);
      });
      let mileageInput = null;
      if (mileageContainer) {
        mileageInput =
          mileageContainer.querySelector(`input#${mileageInputId}`) ||
          mileageContainer.querySelector(`input#${mileageInputIdAlt}`) ||
          mileageContainer.querySelector('input[type="text"]');
      }
      if (mileageInput && mileageInput.tagName.toLowerCase() === 'input') {
        mileageRequired = true;
        mileagePatched = setControlValue(
          mileageInput,
          mileageInputValue,
          (actual, expected) => {
            const expectedDigits = digitsOnly(expected);
            if (!expectedDigits) return asText(actual).trim() === asText(expected).trim();
            return digitsOnly(actual) === expectedDigits;
          },
        );
        mileageHTML = mileageContainer.outerHTML;
      } else {
        const fallbackMileageInput =
          document.querySelector(`input#${mileageInputId}`) ||
          document.querySelector(`input#${mileageInputIdAlt}`);
        if (fallbackMileageInput) {
          mileageRequired = true;
          mileagePatched = setControlValue(
            fallbackMileageInput,
            mileageInputValue,
            (actual, expected) => {
              const expectedDigits = digitsOnly(expected);
              if (!expectedDigits) return asText(actual).trim() === asText(expected).trim();
              return digitsOnly(actual) === expectedDigits;
            },
          );
          mileageHTML = fallbackMileageInput.outerHTML;
        }
      }

      const descriptionContainer = brandContainers.find((container) => {
        const label = container.querySelector('span');
        return label && (label.textContent || '').trim() === descriptionLabel;
      });
      let descriptionTextarea = null;
      if (descriptionContainer) {
        descriptionTextarea = descriptionContainer.querySelector(`textarea#${descriptionTextareaId}`) || descriptionContainer.querySelector('textarea');
      }
      if (descriptionTextarea && descriptionTextarea.tagName.toLowerCase() === 'textarea') {
        descriptionRequired = true;
        descriptionPatched = setControlValue(descriptionTextarea, descriptionText);
        descriptionHTML = descriptionContainer.outerHTML;
      } else {
        const fallbackDescriptionTextarea = document.querySelector(`textarea#${descriptionTextareaId}`);
        if (fallbackDescriptionTextarea) {
          descriptionRequired = true;
          descriptionPatched = setControlValue(fallbackDescriptionTextarea, descriptionText);
          descriptionHTML = fallbackDescriptionTextarea.outerHTML;
        }
      }

      const locationContainers = Array.from(document.querySelectorAll('div.xjbqb8w.x1iyjqo2.x193iq5w.xeuugli.x1n2onr6'));
      for (const container of locationContainers) {
        const label = container.querySelector('span');
        if (!label) continue;
        if ((label.textContent || '').trim() !== locationLabel) continue;

        const input = container.querySelector('input[role="combobox"][aria-label="Lokasi"]');
        if (!input) continue;

        const locationValueOk = setControlValue(input, locationText);
        input.setAttribute('aria-describedby', '_r_2h_');
        input.setAttribute('tabindex', '0');

        locationPatched = locationValueOk;
        locationOuterHTML = container.outerHTML;
        break;
      }

      const yearPatchedCount = [yearPatched, secondYearPatched, thirdYearPatched].filter(Boolean).length;
      const toyotaGroupOk = (!makeRequired && !toyotaInputRequired) || makePatched || toyotaInputPatched;
      const vehicleTypeGroupOk = !vehicleTypeRequired || vehicleTypePatched;
      const yearFieldGroupOk = !yearFieldRequired || yearFieldPatched;
      // Model persistence is finalized by enforce_model_input_commit() in Python.
      const modelGroupOk = true;
      const priceGroupOk = !priceRequired || pricePatched;
      const mileageGroupOk = !mileageRequired || mileagePatched;
      const descriptionGroupOk = !descriptionRequired || descriptionPatched;

      const legacyVehicleOk = vehiclePatched || vehicleTypeGroupOk;
      const legacyYearOk = yearPatchedCount >= 1 || yearFieldGroupOk;

      return {
        ok: legacyVehicleOk && legacyYearOk && vehicleTypeGroupOk && yearFieldGroupOk && toyotaGroupOk && modelGroupOk && priceGroupOk && mileageGroupOk && descriptionGroupOk && locationPatched,
        pageReady: true,
        vehiclePatched,
        yearPatched,
        secondYearPatched,
        thirdYearPatched,
        yearPatchedCount,
        makePatched,
        makeRequired,
        toyotaInputPatched,
        toyotaInputRequired,
        toyotaGroupOk,
        vehicleTypePatched,
        vehicleTypeRequired,
        vehicleTypeGroupOk,
        yearFieldPatched,
        yearFieldRequired,
        yearFieldGroupOk,
        modelPatched,
        modelRequired,
        modelGroupOk,
        pricePatched,
        priceRequired,
        priceGroupOk,
        mileagePatched,
        mileageRequired,
        mileageGroupOk,
        descriptionPatched,
        descriptionRequired,
        descriptionGroupOk,
        locationPatched,
        wrapperHTML: vehicleWrapperHTML,
        outerHTML: vehicleOuterHTML,
        yearWrapperHTML: yearWrapperHTML,
        yearHTML: yearOuterHTML,
        secondYearWrapperHTML: secondYearWrapperHTML,
        secondYearHTML: secondYearOuterHTML,
        thirdYearWrapperHTML: thirdYearWrapperHTML,
        thirdYearHTML: thirdYearOuterHTML,
        makeHTML: makeOuterHTML,
        toyotaInputHTML: toyotaInputHTML,
        vehicleTypeHTML: vehicleTypeHTML,
        yearFieldHTML: yearFieldHTML,
        modelHTML: modelHTML,
        priceHTML: priceHTML,
        mileageHTML: mileageHTML,
        descriptionHTML: descriptionHTML,
        locationHTML: locationOuterHTML,
      };
    }
    """
    result = page.evaluate(
        script,
        {
            "divClass": DIV_CLASS,
            "targetText": TARGET_TEXT,
            "vehicleTypeLabel": VEHICLE_TYPE_LABEL,
            "vehicleTypeWrapperId": VEHICLE_TYPE_WRAPPER_ID,
            "vehicleTypeWrapperIdAlt": VEHICLE_TYPE_WRAPPER_ID_ALT,
            "vehicleTypeWrapperIdAlt2": VEHICLE_TYPE_WRAPPER_ID_ALT2,
            "vehicleTypeWrapperIdAlt3": VEHICLE_TYPE_WRAPPER_ID_ALT3,
            "yearFieldLabel": YEAR_FIELD_LABEL,
            "yearFieldWrapperId": YEAR_FIELD_WRAPPER_ID,
            "yearFieldWrapperIdAlt": YEAR_FIELD_WRAPPER_ID_ALT,
            "targetYearText": TARGET_YEAR_TEXT,
            "makeInputId": MAKE_INPUT_ID,
            "makeInputValue": MAKE_INPUT_VALUE,
            "toyotaInputId": TOYOTA_INPUT_ID,
            "toyotaInputValue": TOYOTA_INPUT_VALUE,
            "brandLabel": BRAND_LABEL,
            "brandInputId": BRAND_INPUT_ID,
            "brandWrapperId": BRAND_WRAPPER_ID,
            "modelLabel": MODEL_LABEL,
            "modelInputId": MODEL_INPUT_ID,
            "modelInputIdAlt": MODEL_INPUT_ID_ALT,
            "modelInputIdAlt2": MODEL_INPUT_ID_ALT2,
            "modelInputValue": MODEL_INPUT_VALUE,
            "priceLabel": PRICE_LABEL,
            "priceInputId": PRICE_INPUT_ID,
            "priceInputValue": PRICE_INPUT_VALUE,
            "mileageLabel": MILEAGE_LABEL,
            "mileageInputId": MILEAGE_INPUT_ID,
            "mileageInputIdAlt": MILEAGE_INPUT_ID_ALT,
            "mileageInputValue": MILEAGE_INPUT_VALUE,
            "descriptionLabel": DESCRIPTION_LABEL,
            "descriptionTextareaId": DESCRIPTION_TEXTAREA_ID,
            "descriptionText": DESCRIPTION_TEXT,
            "attrName": attr_name,
            "attrValue": attr_value,
            "locationLabel": LOCATION_LABEL,
            "locationText": LOCATION_TEXT,
        },
    )
    if result and result.get("ok"):
        print("[OK] DOM updated")
        if result.get("wrapperHTML"):
            print(result.get("wrapperHTML", ""))
        print(result.get("outerHTML", ""))
        if result.get("yearWrapperHTML"):
            print(result.get("yearWrapperHTML", ""))
        if result.get("yearHTML"):
            print(result.get("yearHTML", ""))
        if result.get("secondYearWrapperHTML"):
            print(result.get("secondYearWrapperHTML", ""))
        if result.get("secondYearHTML"):
            print(result.get("secondYearHTML", ""))
        if result.get("thirdYearWrapperHTML"):
            print(result.get("thirdYearWrapperHTML", ""))
        if result.get("thirdYearHTML"):
            print(result.get("thirdYearHTML", ""))
        if result.get("makeHTML"):
            print(result.get("makeHTML", ""))
        if result.get("toyotaInputHTML"):
            print(result.get("toyotaInputHTML", ""))
        if result.get("vehicleTypeHTML"):
            print(result.get("vehicleTypeHTML", ""))
        if result.get("yearFieldHTML"):
            print(result.get("yearFieldHTML", ""))
        if result.get("modelHTML"):
            print(result.get("modelHTML", ""))
        if result.get("priceHTML"):
            print(result.get("priceHTML", ""))
        if result.get("mileageHTML"):
            print(result.get("mileageHTML", ""))
        if result.get("descriptionHTML"):
            print(result.get("descriptionHTML", ""))
        if result.get("locationHTML"):
            print(result.get("locationHTML", ""))
        return True
    if result and not result.get("pageReady", True):
        print(
            "[INFO] waiting for Marketplace form to render:",
            f"url={result.get('url', page.url)}",
            f"title={result.get('title', '')}",
        )
        return False
    if result:
        print(
            "[WARN] partial update:",
            f"vehiclePatched={result.get('vehiclePatched')}",
            f"yearPatched={result.get('yearPatched')}",
            f"secondYearPatched={result.get('secondYearPatched')}",
            f"thirdYearPatched={result.get('thirdYearPatched')}",
            f"makePatched={result.get('makePatched')}",
            f"makeRequired={result.get('makeRequired')}",
            f"toyotaInputPatched={result.get('toyotaInputPatched')}",
            f"toyotaInputRequired={result.get('toyotaInputRequired')}",
            f"toyotaGroupOk={result.get('toyotaGroupOk')}",
            f"vehicleTypePatched={result.get('vehicleTypePatched')}",
            f"vehicleTypeRequired={result.get('vehicleTypeRequired')}",
            f"vehicleTypeGroupOk={result.get('vehicleTypeGroupOk')}",
            f"yearFieldPatched={result.get('yearFieldPatched')}",
            f"yearFieldRequired={result.get('yearFieldRequired')}",
            f"yearFieldGroupOk={result.get('yearFieldGroupOk')}",
            f"modelPatched={result.get('modelPatched')}",
            f"modelRequired={result.get('modelRequired')}",
            f"modelGroupOk={result.get('modelGroupOk')}",
            f"pricePatched={result.get('pricePatched')}",
            f"priceRequired={result.get('priceRequired')}",
            f"priceGroupOk={result.get('priceGroupOk')}",
            f"mileagePatched={result.get('mileagePatched')}",
            f"mileageRequired={result.get('mileageRequired')}",
            f"mileageGroupOk={result.get('mileageGroupOk')}",
            f"descriptionPatched={result.get('descriptionPatched')}",
            f"descriptionRequired={result.get('descriptionRequired')}",
            f"descriptionGroupOk={result.get('descriptionGroupOk')}",
            f"locationPatched={result.get('locationPatched')}",
        )
    return False


@dataclass
class ListingConfig:
    target_url: str
    selling_url: str
    photo_path: Path
    vehicle_type: str
    year: str
    make: str
    model: str
    price: str
    mileage: str
    description: str
    location: str

    @property
    def select_fields(self) -> tuple[tuple[str, str], ...]:
        return (
            (VEHICLE_TYPE_LABEL, self.vehicle_type),
            (YEAR_FIELD_LABEL, self.year),
            (BRAND_LABEL, self.make),
        )


def build_listing_config(
    listing: dict,
    args: argparse.Namespace,
    project_root: Path,
    default_target_url: str,
    default_selling_url: str,
) -> ListingConfig | None:
    vehicle_type = _pick_listing_value(listing, ("vehicle_type", "jenis_kendaraan"), TARGET_TEXT)
    year = _pick_listing_value(listing, ("year", "tahun"), TARGET_YEAR_TEXT)
    make = _pick_listing_value(listing, ("make", "merek", "merk", "brand"), TOYOTA_INPUT_VALUE)
    model = _pick_listing_value(listing, ("model",), MODEL_INPUT_VALUE)
    price = _pick_listing_value(listing, ("price", "harga"), PRICE_INPUT_VALUE)
    mileage = _pick_listing_value(listing, ("mileage", "jarak_tempuh", "jarak"), MILEAGE_INPUT_VALUE)
    description = _pick_listing_value(listing, ("description", "keterangan"), DESCRIPTION_TEXT)
    location = _pick_listing_value(listing, ("location", "lokasi"), LOCATION_TEXT)
    target_url = _pick_listing_value(listing, ("target_url",), default_target_url)
    selling_url = _pick_listing_value(listing, ("selling_url",), default_selling_url)
    listing_photo_arg = _pick_listing_value(listing, ("photo_path",), args.photo_path)
    photo_path = resolve_photo_path(project_root, listing_photo_arg)
    if not photo_path:
        return None
    return ListingConfig(
        target_url=target_url,
        selling_url=selling_url,
        photo_path=photo_path,
        vehicle_type=vehicle_type,
        year=year,
        make=make,
        model=model,
        price=price,
        mileage=mileage,
        description=description,
        location=location,
    )


def apply_listing_globals(config: ListingConfig) -> None:
    global TARGET_TEXT
    global TARGET_YEAR_TEXT
    global MAKE_INPUT_VALUE
    global TOYOTA_INPUT_VALUE
    global MODEL_INPUT_VALUE
    global PRICE_INPUT_VALUE
    global MILEAGE_INPUT_VALUE
    global DESCRIPTION_TEXT
    global LOCATION_TEXT

    TARGET_TEXT = config.vehicle_type
    TARGET_YEAR_TEXT = config.year
    TOYOTA_INPUT_VALUE = config.make
    MODEL_INPUT_VALUE = config.model
    PRICE_INPUT_VALUE = config.price
    MILEAGE_INPUT_VALUE = config.mileage
    DESCRIPTION_TEXT = config.description
    LOCATION_TEXT = config.location
    MAKE_INPUT_VALUE = config.model


def run_single_listing(page, config: ListingConfig, args: argparse.Namespace) -> bool:
    page.goto(config.target_url, wait_until="domcontentloaded")
    print("Opened URL:", config.target_url)
    print("If Facebook login is required, complete login in browser window.")
    next_info = wait_and_find_berikutnya(page, timeout_ms=3000)
    if not next_info.get("found"):
        print(
            "[DEBUG] Berikutnya not actionable on initial load:",
            f"url={next_info.get('url', page.url)}",
            f"total={next_info.get('total')}",
            f"visible={next_info.get('visible')}",
            f"actionable={next_info.get('actionable')}",
            f"sample={next_info.get('sample')}",
        )

    deadline = time.time() + (args.timeout_ms / 1000)
    success = False
    dom_success = False
    photo_success = False
    draft_clicked = False
    leave_clicked = False
    dom_stable_count = 0
    attempts = 0
    selects_ok = False
    model_commit_ok = False
    mileage_commit_ok = False

    while time.time() < deadline:
        try:
            attempts += 1
            page.wait_for_timeout(1500)
            if not photo_success:
                photo_success = upload_photo(page, config.photo_path)
            if "/marketplace/create/vehicle" not in page.url:
                page.goto(config.target_url, wait_until="domcontentloaded")
                page.wait_for_timeout(800)
            dom_success = patch_dom(page, args.attr_name, args.attr_value)
            if dom_success:
                dom_stable_count += 1
            else:
                dom_stable_count = 0
            if not dom_success and attempts % 6 == 0:
                dbg = wait_and_find_berikutnya(page, timeout_ms=800)
                print(
                    "[DEBUG] Berikutnya diagnostics:",
                    f"attempt={attempts}",
                    f"url={page.url}",
                    f"total={dbg.get('total')}",
                    f"visible={dbg.get('visible')}",
                    f"actionable={dbg.get('actionable')}",
                )
            if dom_stable_count >= 2:
                selects_ok = enforce_select_fields(page, config.select_fields)
                model_commit_ok = enforce_model_input_commit(page, MODEL_LABEL, config.model)
                mileage_commit_ok = enforce_labeled_text_input_commit(
                    page, MILEAGE_LABEL, config.mileage, digits_only=True
                )
            if dom_stable_count >= 2 and photo_success and selects_ok and model_commit_ok and mileage_commit_ok and not draft_clicked:
                draft_clicked = click_save_draft(page)
            if draft_clicked and not leave_clicked:
                leave_clicked = click_tinggalkan_halaman(page)
            success = (
                dom_success
                and photo_success
                and selects_ok
                and model_commit_ok
                and mileage_commit_ok
                and draft_clicked
                and leave_clicked
            )
            if success:
                break
        except PlaywrightTimeoutError:
            pass
        except Exception as exc:  # keep retrying while React page loads/changes
            print(f"[WARN] retrying after transient error: {exc}")

    if not success:
        print(
            "[ERROR] incomplete update:",
            f"dom_success={dom_success}",
            f"photo_success={photo_success}",
            f"selects_ok={selects_ok}",
            f"model_commit_ok={model_commit_ok}",
            f"mileage_commit_ok={mileage_commit_ok}",
            f"draft_clicked={draft_clicked}",
            f"leave_clicked={leave_clicked}",
        )
        return False
    return True


def main() -> int:
    args = parse_args()
    project_root = Path.cwd().resolve()
    profile_dir = str(Path(args.profile_dir).resolve())
    data_file = Path(args.data_file).resolve()
    cookies_file = Path(args.cookies_file).resolve()
    listings = load_listings_data(data_file)
    if not listings:
        print(f"[INFO] data file not found/empty, fallback to single run: {data_file}")
        listings = [{}]
    raw_cookies = load_raw_cookies(cookies_file)
    if not raw_cookies:
        print(f"[WARN] no cookies loaded from: {cookies_file}")

    default_target_url = TARGET_URL
    default_selling_url = SELLING_URL

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=args.headless,
            viewport={"width": 1400, "height": 900},
        )
        if raw_cookies:
            context.add_cookies(normalize_cookies(raw_cookies))
        page = context.pages[0] if context.pages else context.new_page()
        failed_count = 0

        for idx, listing in enumerate(listings, start=1):
            config = build_listing_config(
                listing=listing,
                args=args,
                project_root=project_root,
                default_target_url=default_target_url,
                default_selling_url=default_selling_url,
            )
            if not config:
                print(f"[ERROR] listing#{idx} no image found. Provide photo_path in data file or --photo-path.")
                failed_count += 1
                continue

            print(f"[INFO] listing#{idx}/{len(listings)} start")
            apply_listing_globals(config)
            success = run_single_listing(page, config, args)
            if not success:
                print(f"[ERROR] incomplete update listing#{idx}")
                failed_count += 1
                continue

            print("Opening selling page:", config.selling_url)
            page.goto(config.selling_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

        if failed_count > 0:
            print(f"[ERROR] completed with failures: {failed_count}/{len(listings)}")
            context.close()
            return 1

        print("All listings posted. Keeping browser open for 20 seconds...")
        page.wait_for_timeout(20000)
        context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
