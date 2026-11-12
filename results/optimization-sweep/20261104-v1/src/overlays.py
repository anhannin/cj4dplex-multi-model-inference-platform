"""Reversible template-only experiment overlays. Never mutate input objects."""
import copy


def candidate_template(original, candidate, model, root):
    if candidate not in {'control', 'affinity', 'dds', 'mps', 'mps-q75', 'mps-q50', 'mps-q25', 'trt', 'trt-dds', 'trt-mps-q75', 'trt-dds-mps-q75', 'trt-mps-q50', 'trt-dds-mps-q50', 'dds-mps-q50'}:
        raise ValueError(candidate)
    features = candidate.split('-')
    t = copy.deepcopy(original)
    c = t['spec']['containers'][0]
    if candidate == 'control':
        return t
    if candidate == 'affinity':
        cores = '5-9' if model == 'qwen' else '15-19'
        c['command'] = ['/bin/bash', '-c', f'source /opt/ros/jazzy/setup.bash && exec taskset -c {cores} python /app/ros2/{model}_node.py']
    if ('dds' in features or 'trt' in features):
        t['spec']['volumes'].append({'name': 'experiment', 'hostPath': {'path': root, 'type': 'Directory'}})
        c['volumeMounts'].append({'name': 'experiment', 'mountPath': '/experiment', 'readOnly': True})
    if 'dds' in features:
        c['env'].append({'name': 'FASTRTPS_DEFAULT_PROFILES_FILE', 'value': '/experiment/config/low-latency.xml'})
    if 'mps' in features:
        t['spec']['volumes'].append({'name': 'mps-pipe', 'hostPath': {'path': root + '/mps-pipe', 'type': 'Directory'}})
        c['volumeMounts'].append({'name': 'mps-pipe', 'mountPath': root + '/mps-pipe'})
        c['env'].append({'name': 'CUDA_MPS_PIPE_DIRECTORY', 'value': root + '/mps-pipe'})
        quota = next((part[1:] for part in features if part.startswith('q')), None)
        if quota:
            cap = quota if model == 'qwen' else '100'
            c['env'].append({'name': 'CUDA_MPS_ACTIVE_THREAD_PERCENTAGE', 'value': cap})
    if 'trt' in features and model == 'yolo':
        c['command'] = ['/bin/bash', '-c', 'source /opt/ros/jazzy/setup.bash && exec python /experiment/src/yolo_trt_node.py --ros-args -p model_path:=/experiment/engine/yolo26l.engine']
    return t


def template_patch(template):
    """Atomic replace: merge patches would retain experiment-only annotations."""
    return [{'op': 'replace', 'path': '/spec/template', 'value': copy.deepcopy(template)}]
