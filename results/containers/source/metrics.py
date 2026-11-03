"""Dependency-free exploration summaries; milliseconds and linear percentiles."""
def summarize(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'mean_ms': None, 'p50_ms': None, 'p95_ms': None}
    def percentile(q):
        position = (len(values) - 1) * q
        low = int(position)
        high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (position - low)
    return {'n': len(values), 'mean_ms': sum(values) / len(values),
            'p50_ms': percentile(.5), 'p95_ms': percentile(.95)}


def overlapping(rows, start, end):
    """Keep requests fully contained in the shared active measurement interval."""
    return [row for row in rows if row['start'] >= start and row['end'] <= end]
