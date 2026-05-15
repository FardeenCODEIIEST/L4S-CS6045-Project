import threading

from traffic import recv, send_classic, send_l4s


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self):
        return 0


def test_l4s_sender_uses_expected_iptables_rewrite_rule():
    assert send_l4s.IPTABLES_ADD == [
        "iptables",
        "-t",
        "mangle",
        "-A",
        "POSTROUTING",
        "-p",
        "tcp",
        "-j",
        "TOS",
        "--set-tos",
        "0x01/0x03",
    ]
    assert send_l4s.IPTABLES_DEL == [
        "iptables",
        "-t",
        "mangle",
        "-D",
        "POSTROUTING",
        "-p",
        "tcp",
        "-j",
        "TOS",
        "--set-tos",
        "0x01/0x03",
    ]


def test_l4s_sender_builds_iperf3_client_command(monkeypatch):
    captured = {}

    def fake_popen(cmd):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(send_l4s.subprocess, "Popen", fake_popen)

    send_l4s.run_iperf3("10.0.0.5", 5201, 4.5, 30.2, 2, "l4s.json")

    assert captured["cmd"] == [
        "iperf3",
        "-4",
        "-c",
        "10.0.0.5",
        "-p",
        "5201",
        "-b",
        "4.5M",
        "-t",
        "30",
        "-P",
        "2",
        "-C",
        "dctcp",
        "-J",
        "--logfile",
        "l4s.json",
    ]


def test_classic_sender_selects_expected_sysctls():
    assert send_classic.SYSCTL_CUBIC_ECN == {
        "net.ipv4.tcp_congestion_control": "cubic",
        "net.ipv4.tcp_ecn": "1",
    }
    assert send_classic.SYSCTL_CUBIC_NO_ECN == {
        "net.ipv4.tcp_congestion_control": "cubic",
        "net.ipv4.tcp_ecn": "0",
    }


def test_classic_sender_builds_iperf3_client_command(monkeypatch):
    captured = {}

    def fake_popen(cmd):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(send_classic.subprocess, "Popen", fake_popen)

    send_classic.run_iperf3("10.0.0.5", 5202, 3.25, 15.9, 1, "classic.json")

    assert captured["cmd"] == [
        "iperf3",
        "-4",
        "-c",
        "10.0.0.5",
        "-p",
        "5202",
        "-b",
        "3.25M",
        "-t",
        "15",
        "-P",
        "1",
        "-C",
        "cubic",
        "-J",
        "--logfile",
        "classic.json",
    ]


def test_receiver_builds_tcpdump_capture_command(monkeypatch):
    captured = {}
    proc = FakeProcess()

    def fake_popen(cmd, stderr=None):
        captured["cmd"] = cmd
        captured["stderr"] = stderr
        return proc

    monkeypatch.setattr(recv.subprocess, "Popen", fake_popen)
    stop_event = threading.Event()
    stop_event.set()

    recv.run_tcpdump("h5-eth0", [5201, 5202], "capture.pcap", stop_event)

    assert captured["cmd"] == [
        "tcpdump",
        "-i",
        "h5-eth0",
        "-w",
        "capture.pcap",
        "-s",
        "96",
        "--immediate-mode",
        "tcp and (port 5201 or port 5202)",
    ]
    assert proc.terminated
