"""Per-key lighting over HID++ (0x8081 PerKeyLighting v2). Filled in from G HUB's agent."""

PERKEY = 0x8081


def apply(dev, colors):
	"""Not wired yet: the zone numbering and function layout come from G HUB's agent code."""
	raise NotImplementedError('per-key lighting is not implemented yet')
