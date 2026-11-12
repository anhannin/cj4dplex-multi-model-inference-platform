// Diagnostic adapter for CUDA 13.0 Driver API; no PyTorch/library source patch.
// API sequence follows NVIDIA CUDA Green Context documentation.
#include <cuda.h>
#include <cuda_runtime.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <array>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
namespace py = pybind11;

static void check(CUresult code, const char* api) {
    if (code == CUDA_SUCCESS) return;
    const char* name = nullptr; const char* text = nullptr;
    cuGetErrorName(code, &name); cuGetErrorString(code, &text);
    throw std::runtime_error(std::string(api)+": "+(name?name:"unknown")+" "+(text?text:""));
}
#define CU(call) check((call), #call)
static void rtcheck(cudaError_t code, const char* api) {
    if (code != cudaSuccess) throw std::runtime_error(std::string(api)+": "+cudaGetErrorString(code));
}
#define RT(call) rtcheck((call), #call)

__global__ void sample_smid_kernel(unsigned int* output, unsigned long long cycles) {
    unsigned int sm;
    asm volatile("mov.u32 %0, %%smid;" : "=r"(sm));
    if (threadIdx.x == 0) output[blockIdx.x] = sm;
    const auto start = clock64();
    while (clock64() - start < cycles) { }
}

class GreenPair {
    CUdevice device_{};
    CUcontext primary_{};
    std::array<CUgreenCtx,2> contexts_{};
    std::array<CUstream,2> streams_{};
    std::array<CUdevResource,2> parts_{};
    CUdevResource full_{};
    bool retained_ = false;
    bool closed_ = false;
public:
    explicit GreenPair(unsigned int requested) {
        try {
            CU(cuInit(0));
            CU(cuDeviceGet(&device_,0));
            CU(cuDevicePrimaryCtxRetain(&primary_,device_));
            retained_ = true;
            CU(cuCtxSetCurrent(primary_));
            CU(cuDeviceGetDevResource(device_,&full_,CU_DEV_RESOURCE_TYPE_SM));
            if (requested==0 || requested>=full_.sm.smCount)
                throw std::invalid_argument("Require 0 < requested SMs < device SMs");
            unsigned int groups=1;
            CU(cuDevSmResourceSplitByCount(&parts_[0],&groups,&full_,&parts_[1],0,requested));
            if (groups!=1 || parts_[1].sm.smCount==0)
                throw std::runtime_error("No valid complementary partition");
            for (int i=0;i<2;++i) {
                CUdevResourceDesc desc{};
                CU(cuDevResourceGenerateDesc(&desc,&parts_[i],1));
                CU(cuGreenCtxCreate(&contexts_[i],desc,device_,CU_GREEN_CTX_DEFAULT_STREAM));
                CU(cuGreenCtxStreamCreate(&streams_[i],contexts_[i],CU_STREAM_NON_BLOCKING,0));
                // Verify the stream itself, not an environment-variable setting.
                CUgreenCtx owner{};
                CU(cuStreamGetGreenCtx(streams_[i],&owner));
                if (owner!=contexts_[i]) throw std::runtime_error("Stream green-context mismatch");
            }
        } catch (...) { close(); throw; }
    }
    GreenPair(const GreenPair&) = delete;
    GreenPair& operator=(const GreenPair&) = delete;
    ~GreenPair() { close(); }
    void close() noexcept {
        if (closed_) return;
        closed_ = true;
        for (int i=0;i<2;++i) {
            if (streams_[i]) { cuStreamSynchronize(streams_[i]); cuStreamDestroy(streams_[i]); streams_[i]=nullptr; }
            if (contexts_[i]) { cuGreenCtxDestroy(contexts_[i]); contexts_[i]=nullptr; }
        }
        if (retained_) { cuDevicePrimaryCtxRelease(device_); retained_=false; }
    }
    uintptr_t stream_ptr(int index) const {
        if (closed_ || index<0 || index>=2) throw std::invalid_argument("Invalid partition");
        return reinterpret_cast<uintptr_t>(streams_[index]);
    }
    py::dict metadata() {
        py::dict result;
        result["total_sms"]=full_.sm.smCount;
        result["minimum_partition_sms"]=full_.sm.minSmPartitionSize;
        result["coscheduled_alignment"]=full_.sm.smCoscheduledAlignment;
        py::list parts;
        for (int i=0;i<2;++i) {
            CUdevResource actual{};
            CU(cuGreenCtxGetDevResource(contexts_[i],&actual,CU_DEV_RESOURCE_TYPE_SM));
            py::dict p;
            p["actual_sms"]=actual.sm.smCount;
            p["stream_ptr"]=reinterpret_cast<uintptr_t>(streams_[i]);
            p["green_handle"]=reinterpret_cast<uintptr_t>(contexts_[i]);
            p["stream_owner_verified"]=true;
            parts.append(p);
        }
        result["parts"]=parts;
        return result;
    }
    std::vector<unsigned int> sample_smids(int index, unsigned int blocks=4096) {
        if (index<0 || index>=2 || closed_ || blocks==0 || blocks>65536)
            throw std::invalid_argument("Invalid sample bounds");
        CUdeviceptr buffer{};
        CU(cuMemAlloc(&buffer,blocks*sizeof(unsigned int)));
        try {
            sample_smid_kernel<<<blocks,32,0,reinterpret_cast<cudaStream_t>(streams_[index])>>>(
                reinterpret_cast<unsigned int*>(buffer),10000);
            RT(cudaGetLastError());
            CU(cuStreamSynchronize(streams_[index]));
            std::vector<unsigned int> ids(blocks);
            CU(cuMemcpyDtoH(ids.data(),buffer,blocks*sizeof(unsigned int)));
            CU(cuMemFree(buffer));
            std::set<unsigned int> unique(ids.begin(),ids.end());
            return {unique.begin(),unique.end()};
        } catch (...) { cuMemFree(buffer); throw; }
    }
};
PYBIND11_MODULE(green_bridge,m) {
    py::class_<GreenPair>(m,"GreenPair")
        .def(py::init<unsigned int>())
        .def("metadata",&GreenPair::metadata)
        .def("stream_ptr",&GreenPair::stream_ptr)
        .def("sample_smids",&GreenPair::sample_smids,py::arg("index"),py::arg("blocks")=4096)
        .def("close",&GreenPair::close);
}
