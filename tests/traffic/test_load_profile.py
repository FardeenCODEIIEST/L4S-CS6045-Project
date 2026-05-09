import pytest

from traffic import load_profile


def test_steady_profile_splits_bandwidth_by_l4s_fraction():
    stages = load_profile.build_steady(bw=10, l4s_frac=0.4, duration=60)

    assert stages == [
        {"start": 0, "l4s_bw": 4.0, "classic_bw": 6.0, "duration": 60}
    ]


def test_ramp_profile_uses_five_increasing_steps():
    stages = load_profile.build_ramp(bw=10, l4s_frac=0.5, duration=50)

    assert len(stages) == 5
    assert stages[0] == {
        "start": 0,
        "l4s_bw": pytest.approx(0.5),
        "classic_bw": pytest.approx(0.5),
        "duration": 10,
    }
    assert stages[-1] == {
        "start": 40,
        "l4s_bw": pytest.approx(5.0),
        "classic_bw": pytest.approx(5.0),
        "duration": 10,
    }


def test_step_profile_moves_from_normal_load_to_overload():
    stages = load_profile.build_step(bw=10, l4s_frac=0.5, duration=20)

    assert stages == [
        {"start": 0, "l4s_bw": 4.0, "classic_bw": 4.0, "duration": 10},
        {"start": 10, "l4s_bw": 7.5, "classic_bw": 7.5, "duration": 10},
    ]


def test_burst_profile_alternates_class_pressure():
    stages = load_profile.build_burst(bw=10, l4s_frac=0.5, duration=40)

    assert len(stages) == 4
    assert stages[0]["l4s_bw"] == 10
    assert stages[0]["classic_bw"] == 5
    assert stages[2]["l4s_bw"] == 5
    assert stages[2]["classic_bw"] == 10


def test_mixed_profile_combines_ramp_overload_and_l4s_spike():
    stages = load_profile.build_mixed(bw=10, l4s_frac=0.5, duration=100)

    assert stages == [
        {"start": 0, "l4s_bw": 2.5, "classic_bw": 2.5, "duration": 30},
        {"start": 30, "l4s_bw": 6.5, "classic_bw": 6.5, "duration": 40},
        {"start": 70, "l4s_bw": 10.0, "classic_bw": 4.0, "duration": 30},
    ]


@pytest.mark.parametrize("fraction", [0.0, 1.0])
def test_main_rejects_l4s_fraction_boundaries(monkeypatch, capsys, fraction):
    monkeypatch.setattr(
        "sys.argv",
        [
            "load_profile.py",
            "--dst",
            "10.0.0.5",
            "--l4s-fraction",
            str(fraction),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        load_profile.main()

    assert exc.value.code == 1
    assert "--l4s-fraction must be strictly between 0 and 1" in capsys.readouterr().out
