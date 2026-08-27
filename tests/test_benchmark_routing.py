from benchmark.harness.report import render
from benchmark.harness.run import effective_max_parallel


def test_effective_max_parallel_uses_last_override():
    assert effective_max_parallel(["--auto"]) == 1
    assert effective_max_parallel(
        ["--max-parallel", "2", "--auto", "--max-parallel=3"]
    ) == 3


def test_report_describes_actual_routing_and_loaded_context():
    results = {
        "run_id": "route-test",
        "meta": {
            "model": {"key": "qwen/test", "max_context_length": 131072},
            "loaded_context_length": 32768,
            "agent_args": ["--auto", "--max-parallel", "3"],
            "routing_policy_version": "auto-v2",
            "effective_max_parallel": 3,
            "trials_per_task": 1,
        },
        "trials": [{
            "task_id": "L1-01", "level": 1, "trial": 0, "resolved": True,
            "score": 1.0, "wall_s": 1.0, "requests": 2, "timeout": False,
            "p2p_tampered": False,
            "subscores": {"f2p": 1.0, "p2p": 1.0, "localization": 1.0,
                          "minimality": 1.0, "gate": 1.0},
            "routing": {"events": [{"phase": "initial", "selected": "investigate",
                                      "executed": True}]},
        }],
    }
    report = render(results)
    assert "Context**: 32,768 tokens" in report
    assert "investigate 1" in report
    assert "Configured worker cap**: 3" in report
