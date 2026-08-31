import os
from pathlib import Path

import keep_focused.hosts as hosts_mod
from keep_focused.hosts import (
    apply_block,
    clear_block,
    expand_domains,
    get_blocked_from_hosts,
    is_block_active,
    normalize_domain,
)


def test_normalize_domain():
    assert normalize_domain("https://www.Facebook.com/") == "facebook.com"
    assert normalize_domain("http://x.com:8080/path?query=1") == "x.com"
    assert normalize_domain("WWW.LINKEDIN.COM") == "linkedin.com"
    assert normalize_domain(" spotify.com ") == "spotify.com"
    assert normalize_domain(".facebook.com") == "facebook.com"
    assert normalize_domain("www.example.com") == "example.com"
    assert normalize_domain("m.facebook.com") == "m.facebook.com"


def test_expand_domains():
    assert set(expand_domains(["facebook.com"])) == {"facebook.com", "www.facebook.com"}
    # www input should still give both
    assert set(expand_domains(["www.facebook.com"])) == {"facebook.com", "www.facebook.com"}
    # invalid
    assert expand_domains(["notadomain"]) == []
    assert expand_domains([""]) == []


def test_hosts_block_and_clear(tmp_env):
    hosts = tmp_env["hosts"]
    apply_block(["facebook.com", "x.com"], enabled=True)
    content = hosts.read_text()
    assert "facebook.com" in content
    assert "www.facebook.com" in content
    assert "x.com" in content
    assert "www.x.com" in content
    assert is_block_active()
    assert "facebook.com" in get_blocked_from_hosts()

    # Disable should clear
    apply_block(["facebook.com"], enabled=False)
    assert "facebook.com" not in hosts.read_text()
    assert not is_block_active()

    # Re-enable then clear
    apply_block(["linkedin.com"], enabled=True)
    assert "linkedin.com" in hosts.read_text()
    clear_block()
    assert not is_block_active()
    assert "# BEGIN keep-focused" not in hosts.read_text()


def test_hosts_preserves_other_content(tmp_env):
    hosts = tmp_env["hosts"]
    hosts.write_text("127.0.0.1 localhost\n192.168.1.1 myhost\n")
    apply_block(["example.com"], enabled=True)
    content = hosts.read_text()
    assert "localhost" in content
    assert "myhost" in content
    assert "example.com" in content
    # Apply again should not duplicate markers
    apply_block(["example.com", "facebook.com"], enabled=True)
    content2 = hosts.read_text()
    assert content2.count("# BEGIN keep-focused") == 1
    assert content2.count("# END keep-focused") == 1
    # Clear preserves other
    clear_block()
    content3 = hosts.read_text()
    assert "localhost" in content3
    assert "# BEGIN" not in content3


def test_hosts_no_duplicate_on_reapply(tmp_env):
    hosts = tmp_env["hosts"]
    apply_block(["example.com", "facebook.com"], enabled=True)
    apply_block(["example.com", "facebook.com"], enabled=True)
    assert hosts.read_text().count("# BEGIN keep-focused") == 1
