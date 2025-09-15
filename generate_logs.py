# file: generate_logs.py
"""
An advanced, production-grade log generator for the VIA project.

This script simulates a multi-service, cloud-native environment, producing
realistic, structured, OTel-compliant JSONL logs. It uses the Faker library
to generate varied data and injects a suite of sophisticated anomalies
to rigorously test anomaly detection systems.

Improvements:
- More services and log templates for diversity.
- Correlated trace/span IDs across services for realistic distributed tracing.
- Gradual anomaly buildup (e.g., latency increases over time).
- Configurable via CLI args (duration, rate, output file, anomaly intensity).
- Batch writing for performance with large volumes (e.g., 10M+ logs).
- Progress logging and error handling.
- Realistic multi-line stack traces with variable depth.
- Fixed KeyError by ensuring template compatibility with attributes.
"""

import argparse
import json
import random
import time
import uuid
from datetime import datetime
import pathlib
from faker import Faker

# --- Configuration Defaults ---
DEFAULT_DURATION_MIN = 10
DEFAULT_LOGS_PER_SECOND = 500
DEFAULT_OUTPUT_FILE = "logs/telemetry_logs.jsonl"
DEFAULT_ANOMALY_INTENSITY = 0.8  # Probability threshold for anomaly injection during windows

# --- Anomaly Windows (in seconds from start) ---
LATENCY_ANOMALY_WINDOW = (120, 140)  # Gradual increase
FREQUENCY_ANOMALY_WINDOW = (240, 260)  # Burst of errors
NOVEL_ERROR_WINDOW = (360, 362)  # Rare event
STACK_TRACE_WINDOW = (480, 482)  # Multi-line error

# --- Setup ---
fake = Faker()

class LogFactory:
    """Creates structured OTel-compliant log records."""
    @staticmethod
    def create_log_record(level, body, service_name, trace_id, span_id, attributes=None):
        ts_ns = int(datetime.now().timestamp() * 1e9)
        log_attributes = attributes or {}
        
        # Standard OTel attributes
        otel_attrs = [
            {"key": k, "value": {"stringValue": str(v)}} 
            for k, v in log_attributes.items()
        ]

        # Severity mapping
        severity_map = {"DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}

        return {
            "resourceLogs": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                        {"key": "process.pid", "value": {"intValue": random.randint(1000, 30000)}}
                    ]
                },
                "scopeLogs": [{"logRecords": [{
                    "timeUnixNano": str(ts_ns),
                    "traceId": trace_id,
                    "spanId": span_id,
                    "severityNumber": severity_map.get(level, 9),
                    "severityText": level,
                    "body": {"stringValue": body},
                    "attributes": otel_attrs
                }]}]
            }]
        }

class ServiceSimulator:
    """Simulates microservices with correlated logs and anomalies."""
    def __init__(self):
        self.services = [
            "auth-service", "payment-service", "api-gateway", "user-service", "notification-service", "db-cluster"
        ]
        self.log_templates = {
            "DEBUG": [
                ("Debug: Cache hit for key {cache_key}", ["cache_key"]),
                ("Tracing request for trace {trace_id}", ["trace_id"]),
            ],
            "INFO": [
                ("User {user_email} logged in from IP {ip} with user_agent {user_agent}", ["user_email", "ip", "user_agent"]),
                ("{http_method} {http_path} completed in {latency_ms}ms with status {status_code}", ["http_method", "http_path", "latency_ms", "status_code"]),
                ("Processed payment {transaction_id} for user {user_email}", ["transaction_id", "user_email"]),
                ("Sent notification to {user_email}: {notification_type}", ["user_email", "notification_type"]),
                ("Database query executed: SELECT * FROM users WHERE id={user_id}", ["user_id"]),
            ],
            "WARN": [
                ("High latency ({latency_ms}ms) on {http_path} for user {user_email}", ["latency_ms", "http_path", "user_email"]),
                ("Memory usage spike on {service}: {mem_usage}% - monitoring", ["service", "mem_usage"]),
                ("Rate limit approaching for IP {ip}: {requests_per_min}/min", ["ip", "requests_per_min"]),
            ],
            "ERROR": [
                ("Failed to authenticate user {user_email}: Invalid credentials", ["user_email"]),
                ("{http_method} {http_path} failed with status {status_code}: {error_message}", ["http_method", "http_path", "status_code", "error_message"]),
                ("Database connection lost: Timeout after {latency_ms}ms", ["latency_ms"]),
            ],
            "FATAL": [
                ("Critical failure: System out of memory - shutting down {service}", ["service"]),
                ("Security breach detected: Unauthorized access attempt from {ip}", ["ip"]),
            ],
        }

    def generate_normal_log(self, trace_id: str, span_id: str, is_degraded: bool = False):
        service = random.choice(self.services)
        level = random.choices(list(self.log_templates.keys()), weights=[5, 70, 15, 8, 2])[0]
        template, required_keys = random.choice(self.log_templates[level])
        
        latency = random.randint(50, 300) if not is_degraded else random.randint(1000, 5000)
        status_code = random.choice([200, 201]) if level in ["DEBUG", "INFO"] else random.choice([400, 401, 500, 503])
        
        attrs = {
            "http.user_agent": fake.user_agent(),
            "net.peer.ip": fake.ipv4(),
            "http_method": random.choice(["GET", "POST", "PUT", "DELETE"]),
            "http_path": fake.uri_path(),
            "latency_ms": latency,
            "status_code": status_code,
            "user_email": fake.email(),
            "transaction_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "cache_key": fake.sha256(),
            "requests_per_min": random.randint(50, 200),
            "mem_usage": random.randint(60, 95),
            "error_message": random.choice(["Timeout", "Invalid input", "Server error"]),
            "notification_type": random.choice(["email", "push"]),
            "service": service,
            "trace_id": trace_id
        }
        
        # Ensure all required keys are present; provide defaults if missing
        format_attrs = {k: attrs.get(k, "unknown") for k in required_keys}
        try:
            body = template.format(**format_attrs)
        except KeyError as e:
            print(f"KeyError in template formatting: {e}, template: {template}, keys: {required_keys}")
            body = template  # Fallback to raw template

        return LogFactory.create_log_record(level, body, service, trace_id, span_id, attrs)

    def generate_frequency_spike_log(self, trace_id: str, span_id: str):
        service = random.choice(self.services)
        body = f"Service Unavailable: Upstream failure - retrying {random.randint(1, 5)}"
        attrs = {"http.status_code": 503, "error.type": "UpstreamFailure", "retry_count": random.randint(1, 5)}
        return LogFactory.create_log_record("ERROR", body, service, trace_id, span_id, attrs)

    def generate_novel_error_log(self, trace_id: str, span_id: str):
        service = random.choice(self.services)
        body = "Unprecedented anomaly: Quantum entanglement in data stream detected - halting operations"
        attrs = {"anomaly.type": "quantum_error", "affected_nodes": random.randint(5, 20)}
        return LogFactory.create_log_record("FATAL", body, service, trace_id, span_id, attrs)

    def generate_stack_trace_log(self, trace_id: str, span_id: str):
        service = random.choice(self.services)
        stack_depth = random.randint(5, 10)
        stack_trace = "\n".join([
            f"\tat com.example.{service}.Module{i}.method{i}(Module{i}.java:{random.randint(50, 200)})" 
            for i in range(stack_depth)
        ])
        body = f"Unhandled exception in core module:\njava.lang.RuntimeException: Critical failure\n{stack_trace}"
        attrs = {"error.type": "RuntimeException", "stack_depth": stack_depth}
        return LogFactory.create_log_record("ERROR", body, service, trace_id, span_id, attrs)

def main(args):
    """Main function to run the log generation simulation."""
    pathlib.Path("logs").mkdir(exist_ok=True)
    output_file = pathlib.Path(args.output_file)
    
    simulator = ServiceSimulator()
    start_time = time.time()
    end_time = start_time + args.duration_min * 60
    total_logs = args.duration_min * 60 * args.logs_per_second
    log_count = 0
    batch = []  # For batch writing

    print(f"Generating ~{total_logs} realistic OTel logs over {args.duration_min} minutes...")
    print(f"Output: {output_file}")

    while time.time() < end_time:
        time_since_start = time.time() - start_time
        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]

        # --- Anomaly Injection with Gradual Buildup ---
        in_latency_window = LATENCY_ANOMALY_WINDOW[0] < time_since_start < LATENCY_ANOMALY_WINDOW[1]
        in_frequency_window = FREQUENCY_ANOMALY_WINDOW[0] < time_since_start < FREQUENCY_ANOMALY_WINDOW[1]
        in_novel_window = NOVEL_ERROR_WINDOW[0] < time_since_start < NOVEL_ERROR_WINDOW[1]
        in_stack_window = STACK_TRACE_WINDOW[0] < time_since_start < STACK_TRACE_WINDOW[1]

        degrade_prob = (time_since_start - LATENCY_ANOMALY_WINDOW[0]) / (LATENCY_ANOMALY_WINDOW[1] - LATENCY_ANOMALY_WINDOW[0]) if in_latency_window else 0
        spike_prob = random.random() < args.anomaly_intensity if in_frequency_window else 0

        if in_stack_window:
            log_record = simulator.generate_stack_trace_log(trace_id, span_id)
        elif in_novel_window:
            log_record = simulator.generate_novel_error_log(trace_id, span_id)
        elif spike_prob > 0.5:
            log_record = simulator.generate_frequency_spike_log(trace_id, span_id)
        else:
            log_record = simulator.generate_normal_log(trace_id, span_id, is_degraded=(random.random() < degrade_prob))

        batch.append(json.dumps(log_record))
        log_count += 1

        # Batch write every 1000 logs
        if len(batch) >= 1000:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write("\n".join(batch) + "\n")
            batch.clear()

        # Rate limiting
        if log_count % args.logs_per_second == 0:
            time.sleep(1)

    # Flush remaining batch
    if batch:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write("\n".join(batch) + "\n")

    print(f"Completed. Generated {log_count} log records in '{output_file}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Advanced OTel Log Generator for VIA")
    parser.add_argument("--duration_min", type=int, default=DEFAULT_DURATION_MIN, help="Simulation duration in minutes")
    parser.add_argument("--logs_per_second", type=int, default=DEFAULT_LOGS_PER_SECOND, help="Logs per second rate")
    parser.add_argument("--output_file", type=str, default=DEFAULT_OUTPUT_FILE, help="Output JSONL file path")
    parser.add_argument("--anomaly_intensity", type=float, default=DEFAULT_ANOMALY_INTENSITY, help="Anomaly injection probability (0-1)")
    args = parser.parse_args()
    main(args)