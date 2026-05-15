from eval.parse_ecn import parse_tcpdump_text


TCPDUMP_TEXT = """\
1778364563.376556 IP (tos 0x0, ttl 63, id 28847, offset 0, flags [DF], proto TCP (6), length 60)
    10.0.2.3.42544 > 10.0.5.5.5202: Flags [SEW], cksum 0xfab8 (correct), seq 1, win 42340, length 0
1778364563.377161 IP (tos 0x1,ECT(1), ttl 63, id 8165, offset 0, flags [DF], proto TCP (6), length 60)
    10.0.1.1.58142 > 10.0.5.5.5201: Flags [SEW], cksum 0xe757 (correct), seq 2, win 42340, length 0
1778364563.396867 IP (tos 0x2,ECT(0), ttl 63, id 28849, offset 0, flags [DF], proto TCP (6), length 89)
    10.0.2.3.42544 > 10.0.5.5.5202: Flags [P.], seq 1:38, ack 1, win 83, length 37
1778364563.397378 IP (tos 0x3,CE, ttl 63, id 8167, offset 0, flags [DF], proto TCP (6), length 89)
    10.0.1.1.58142 > 10.0.5.5.5201: Flags [P.], seq 1:38, ack 1, win 83, length 37
1778364563.401872 IP (tos 0x0, ttl 64, id 42462, offset 0, flags [DF], proto TCP (6), length 52)
    10.0.5.5.5202 > 10.0.2.3.42544: Flags [.], cksum 0xa362 (correct), ack 38, win 85, length 0
"""


def test_parse_tcpdump_text_counts_forward_ecn_by_class():
    summary = parse_tcpdump_text(TCPDUMP_TEXT)

    l4s = summary["classes"]["l4s"]
    classic = summary["classes"]["classic"]

    assert l4s["packets"] == 2
    assert l4s["payload_packets"] == 1
    assert l4s["payload_bytes"] == 37
    assert l4s["ecn_counts"]["ect1"] == 1
    assert l4s["ecn_counts"]["ce"] == 1
    assert l4s["ce_rate"] == 0.5

    assert classic["packets"] == 2
    assert classic["payload_packets"] == 1
    assert classic["ecn_counts"]["not_ect"] == 1
    assert classic["ecn_counts"]["ect0"] == 1

