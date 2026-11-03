# Single-node Kubernetes installation

Approved scope: install native upstream Kubernetes on Spark, retaining Docker and driver.
Host: spark-e6d6 / 192.168.24.204 / ARM64 / Ubuntu24.04 / cgroup v2.

- kubeadm/kubelet/kubectl 1.37.2, standalone single control-plane/worker node.
- Dedicated containerd-k8s.service using installed containerd2.2 binary, independent
  root/state/socket/config; do not restart or rewrite Docker's containerd configuration.
- Preserve host swap using supported kubelet failSwapOn:false / NoSwap for Pods.
- Flannel0.28.10, Pod10.244/16, Service10.96/12; preserve UFW and SSH rules.
- User kubeconfig stays only at remote ~/.kube/config, chmod600; never copy credentials
  or kubeadm bootstrap logs to repository. Root installation log is root-readable only.
- Verify Ready, CoreDNS/CNI, in-cluster DNS+HTTP and existing Docker GPU access.
- Configure NVIDIA runtime handler/plugin and check allocatable GPU if supported.
- Do not deploy AI services, configure GPU sharing, publish ingress, or join other nodes.
