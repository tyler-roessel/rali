# Sales-to-CX handoff alerts

RALI's synthetic lifecycle has 111 closed-won accounts and 94 onboarded accounts. The difference is 17 accounts for review; six are explicitly labelled as handoff leaks in the generator. The exception mart lists every closed-won account without an onboarding event, including the other 11.

The mart assigns an illustrative CX owner key by territory. `Unknown` and unmapped territories route to `cx_triage`. These keys are demo roles, not employees. A stable notification key identifies the event in the delivery log. The committed 200-account sample has one exception.

The inactive n8n template selects one unlogged exception after its 24-hour handoff due time, looks up its assigned recipient in a private runtime directory, posts an internal Slack alert, and records the accepted message. No restaurant is contacted. Run the two setup files in `sql/`, populate the private directory, connect the workflow, and inspect the selected account before a manual run.

The log prevents ordinary repeat runs. Delivery is not guaranteed exactly once: if Slack accepts a message and the log write fails, a retry can duplicate the alert. Inspect Slack before retrying. The template has no scheduler, live CRM ownership feed, retry queue, or escalation policy. Lifecycle events are synthetic throughout.
