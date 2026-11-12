// Isolated CUDA13 single-Green adapter. Archived GreenPair implementation is untouched.
#include <cuda.h>
#include <cuda_runtime.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
namespace py=pybind11;
static void ck(CUresult e,const char* s){if(e!=CUDA_SUCCESS){const char* n=nullptr;cuGetErrorName(e,&n);throw std::runtime_error(std::string(s)+": "+(n?n:"unknown"));}}
#define CU(x) ck((x),#x)
__global__ void smids(unsigned* out){unsigned sm;asm volatile("mov.u32 %0, %%smid;":"=r"(sm));if(threadIdx.x==0)out[blockIdx.x]=sm;auto t=clock64();while(clock64()-t<10000){}}
class Green {
 CUdevice d_{};CUcontext primary_{};CUgreenCtx green_{};CUstream stream_{};CUdevResource full_{},part_{};bool retained_=false;
public:
 explicit Green(unsigned requested){try{
  CU(cuInit(0));CU(cuDeviceGet(&d_,0));CU(cuDevicePrimaryCtxRetain(&primary_,d_));retained_=true;CU(cuCtxSetCurrent(primary_));
  CU(cuDeviceGetDevResource(d_,&full_,CU_DEV_RESOURCE_TYPE_SM));
  if(requested==0||requested>full_.sm.smCount)throw std::invalid_argument("Invalid requested SM count");
  if(requested==full_.sm.smCount)part_=full_;
  else {unsigned groups=1;CUdevResource remainder{};CU(cuDevSmResourceSplitByCount(&part_,&groups,&full_,&remainder,0,requested));if(groups!=1)throw std::runtime_error("Missing split");}
  if(part_.sm.smCount!=requested)throw std::runtime_error("SM count rounded; refuse mislabeled point");
  CUdevResourceDesc desc{};CU(cuDevResourceGenerateDesc(&desc,&part_,1));CU(cuGreenCtxCreate(&green_,desc,d_,CU_GREEN_CTX_DEFAULT_STREAM));
  CU(cuGreenCtxStreamCreate(&stream_,green_,CU_STREAM_NON_BLOCKING,0));CUgreenCtx owner{};CU(cuStreamGetGreenCtx(stream_,&owner));if(owner!=green_)throw std::runtime_error("Wrong stream owner");
 }catch(...){close();throw;}}
 Green(const Green&)=delete;Green& operator=(const Green&)=delete;~Green(){close();}
 void close()noexcept{if(stream_){cuStreamSynchronize(stream_);cuStreamDestroy(stream_);stream_=nullptr;}if(green_){cuGreenCtxDestroy(green_);green_=nullptr;}if(retained_){cuDevicePrimaryCtxRelease(d_);retained_=false;}}
 uintptr_t stream_ptr()const{return reinterpret_cast<uintptr_t>(stream_);}
 py::dict metadata(){CUdevResource actual{};CU(cuGreenCtxGetDevResource(green_,&actual,CU_DEV_RESOURCE_TYPE_SM));py::dict r;r["actual_sms"]=actual.sm.smCount;r["total_sms"]=full_.sm.smCount;r["minimum_sms"]=full_.sm.minSmPartitionSize;r["alignment"]=full_.sm.smCoscheduledAlignment;r["stream_ptr"]=stream_ptr();r["stream_owner_verified"]=true;return r;}
 std::vector<unsigned> sample_smids(){constexpr unsigned n=4096;CUdeviceptr p{};CU(cuMemAlloc(&p,n*sizeof(unsigned)));try{smids<<<n,32,0,reinterpret_cast<cudaStream_t>(stream_)>>>(reinterpret_cast<unsigned*>(p));auto e=cudaGetLastError();if(e!=cudaSuccess)throw std::runtime_error(cudaGetErrorString(e));CU(cuStreamSynchronize(stream_));std::vector<unsigned> v(n);CU(cuMemcpyDtoH(v.data(),p,n*sizeof(unsigned)));CU(cuMemFree(p));std::set<unsigned> u(v.begin(),v.end());return {u.begin(),u.end()};}catch(...){cuMemFree(p);throw;}}
};
PYBIND11_MODULE(_green_sweep,m){py::class_<Green>(m,"Green").def(py::init<unsigned>()).def("metadata",&Green::metadata).def("stream_ptr",&Green::stream_ptr).def("sample_smids",&Green::sample_smids).def("close",&Green::close);}
