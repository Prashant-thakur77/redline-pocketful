import os
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

URL = os.environ["BASE_URL"]


def reset(value=0):
    assert httpx.post(f"{URL}/reset", json={"value": value}).status_code == 204


def value():
    return httpx.get(f"{URL}/value").json()["value"]


def test_r1_add_one():
    reset(7)
    assert httpx.post(f"{URL}/add", json={"n": 1}).json() == {"value": 8}


def test_r2_add_rejects_zero_and_negative():
    reset()
    for n in (0, -1, "2", True):
        assert httpx.post(f"{URL}/add", json={"n": n}).status_code == 400
    assert value() == 0


def test_r3_retry_with_key_applies_once():
    reset()
    first = httpx.post(f"{URL}/add", json={"n": 5, "key": "k"}).json()
    again = httpx.post(f"{URL}/add", json={"n": 5, "key": "k"}).json()
    assert first == again == {"value": 5} and value() == 5


def test_r4_concurrent_adds_are_not_lost():
    reset()
    with ThreadPoolExecutor(40) as pool:
        list(pool.map(lambda _: httpx.post(f"{URL}/add", json={"n": 2}, timeout=10), range(80)))
    assert value() == 160


def test_r5_page_shows_states_and_fits_narrow_screens():
    page = httpx.get(f"{URL}/")
    assert page.status_code == 200 and 'data-state="loading"' in page.text
    assert all(int(w) <= 400 for w in re.findall(r"width:\s*(\d+)px", page.text))
