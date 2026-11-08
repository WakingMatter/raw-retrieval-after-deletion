from e2.power import n_streams, power, sd_hat


def test_low_sd_keeps_32():
    assert n_streams(0.15)["n"] == 32


def test_high_sd_adds_streams_capped_at_48():
    r = n_streams(0.30)
    assert 32 < r["n"] <= 48 and r["power_n"] >= 0.8 or r["n"] == 48
    assert n_streams(1.0)["n"] == 48


def test_monotone_and_sd_hat_takes_larger():
    assert power(48, 0.25) > power(32, 0.25)
    assert sd_hat({"a": [0.0, 0.1, 0.2, 0.1], "b": [0.0, 0.3, -0.3, 0.0]}) > 0.2
