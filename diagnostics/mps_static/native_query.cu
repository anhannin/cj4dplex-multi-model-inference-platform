#include <cuda_runtime.h>
#include <cstdio>
#define C(x) do { auto e=(x); if(e!=cudaSuccess){fprintf(stderr,"%s: %d %s\n",#x,(int)e,cudaGetErrorString(e));return 1;} } while(0)
__global__ void one(int* p){p[0]=42;}
int main(){int v=0,driver=0; C(cudaRuntimeGetVersion(&v));C(cudaDriverGetVersion(&driver));printf("runtime=%d driver_api=%d\n",v,driver);cudaDeviceProp p;C(cudaGetDeviceProperties(&p,0));printf("visible_sms=%d\n",p.multiProcessorCount);int *d,h;C(cudaMalloc(&d,sizeof(int)));one<<<1,1>>>(d);C(cudaDeviceSynchronize());C(cudaMemcpy(&h,d,sizeof(int),cudaMemcpyDeviceToHost));C(cudaFree(d));printf("kernel_value=%d\n",h);return h==42?0:1;}
