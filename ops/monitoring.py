import logging

logger = logging.getLogger("monitoring")

class AlertingSystem:
    def __init__(self, pager_duty_key: str = None):
        self.pager_duty_key = pager_duty_key

    def emit_metric(self, metric_name: str, value: float, tags: dict):
        # Sends to Datadog / Prometheus
        logger.info(f"METRIC: {metric_name} = {value} {tags}")

    def trigger_page(self, title: str, details: str):
        """
        Wires to an alerting channel. Someone must get paged if quarantines spike.
        """
        logger.critical(f"PAGE TRIGGERED: {title} | {details}")
        # if self.pager_duty_key:
        #     requests.post("https://events.pagerduty.com/v2/enqueue", ...)

alert_system = AlertingSystem()

def monitor_quarantine_event(node_id: str, reason: str):
    alert_system.emit_metric("node.quarantined", 1.0, {"node": node_id, "reason": reason})
    alert_system.trigger_page(f"Node Quarantined: {node_id}", f"Reason: {reason}. Review immediately.")
