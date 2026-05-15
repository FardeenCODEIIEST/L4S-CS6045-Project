from topo.topology import HOSTS, build_runtime_commands, build_simple_switch_command


def test_topology_host_ports_are_stable():
    ports = {spec.name: spec.switch_port for spec in HOSTS}

    assert ports == {
        "h1": 1,
        "h2": 2,
        "h3": 3,
        "h4": 4,
        "h5": 5,
    }


def test_runtime_commands_install_routes_for_every_host():
    commands = build_runtime_commands(l4s_threshold=11, classic_threshold=22)

    for spec in HOSTS:
        assert (
            "table_add IngressImpl.ipv4_lpm IngressImpl.set_nhop "
            f"{spec.ip}/32 => {spec.mac} {spec.gateway_mac} {spec.switch_port}"
        ) in commands
        assert (
            "table_add IngressImpl.l2_forward IngressImpl.set_egress "
            f"{spec.mac} => {spec.switch_port}"
        ) in commands


def test_runtime_commands_initialize_threshold_registers():
    commands = build_runtime_commands(
        l4s_threshold=11,
        classic_threshold=22,
        classic_protection_threshold=7,
    )

    assert "register_write reg_l4s_threshold 0 11" in commands
    assert "register_write reg_classic_threshold 0 22" in commands
    assert "register_write reg_classic_protection_threshold 0 7" in commands
    assert "register_write reg_classic_protection_budget 0 0" in commands


def test_runtime_commands_can_configure_bmv2_receiver_queue():
    commands = build_runtime_commands(
        bmv2_queue_rate_pps=800,
        bmv2_queue_depth_pkts=100,
        bmv2_queue_port=5,
    )

    assert commands[0] == "set_queue_rate 800 5"
    assert commands[1] == "set_queue_depth 100 5"


def test_simple_switch_command_places_target_options_after_separator():
    command = build_simple_switch_command(
        sw_path="simple_switch",
        json_path="build/l4s.json",
        thrift_port=9090,
        priority_queues=2,
        interface_args=("-i", "1@s1-eth1"),
    )

    separator = command.index("--")
    assert command[separator - 1] == "build/l4s.json"
    assert command[separator + 1 :] == ["--priority-queues", "2"]
    assert command.index("-i") < separator


def test_simple_switch_command_can_override_notifications_addr():
    command = build_simple_switch_command(
        sw_path="simple_switch",
        json_path="build/l4s.json",
        thrift_port=9090,
        priority_queues=2,
        notifications_addr="ipc:///tmp/l4s-bmv2-test.ipc",
    )

    separator = command.index("--")
    option_index = command.index("--notifications-addr")
    assert command[option_index + 1] == "ipc:///tmp/l4s-bmv2-test.ipc"
    assert option_index < separator


def test_runtime_commands_initialize_controller_telemetry_registers():
    commands = build_runtime_commands()

    assert "register_write reg_l4s_qdepth 0 0" in commands
    assert "register_write reg_classic_qdepth 0 0" in commands
    assert "register_write reg_l4s_growth 0 0" in commands
    assert "register_write reg_classic_growth 0 0" in commands
