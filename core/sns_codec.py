"""ISAAC-64 for SNS media, from Bob Jenkins' public-domain algorithm.

Reference: https://burtleburtle.net/bob/c/isaac64.c (Bob Jenkins, 1996).
WeChat uses reverse result order and big-endian bytes. Each refill produces
256 *new* words; reusing one result block corrupts all images above 2048 bytes.
"""
import re

MASK=(1<<64)-1


def mix(state):
    shifts=(9,9,23,15,14,20,17,14)
    for i,shift in enumerate(shifts):
        tail=(i+7)&7;target=(i+5)&7
        state[i]=(state[i]-state[(i+4)&7])&MASK
        moved=state[tail]<<shift if i&1 else state[tail]>>shift
        state[target]=(state[target]^moved)&MASK
        state[tail]=(state[tail]+state[i])&MASK
    return state


class Isaac64:
    def __init__(self,seed):
        value=str(seed).strip()
        if not re.fullmatch(r'[0-9]{1,20}',value) or int(value)>MASK:raise ValueError('SNS 媒体参数无效')
        self.memory=[0]*256;initial=[0]*256;initial[0]=int(value)
        state=[0x9e3779b97f4a7c13]*8
        for _ in range(4):mix(state)
        for source in (initial,self.memory):
            for base in range(0,256,8):
                state=[(state[j]+source[base+j])&MASK for j in range(8)]
                mix(state);self.memory[base:base+8]=state
        self.a=self.b=self.c=0;self.results=[];self.position=-1

    def refill(self):
        self.c=(self.c+1)&MASK;a=self.a;b=(self.b+self.c)&MASK;output=[];memory=self.memory
        for i in range(256):
            x=memory[i];step=i&3
            if step==0:a=~(a^(a<<21))
            elif step==1:a^=a>>5
            elif step==2:a^=a<<12
            else:a^=a>>33
            a=((a&MASK)+memory[(i+128)&255])&MASK
            y=(memory[(x>>3)&255]+a+b)&MASK;memory[i]=y
            b=(memory[(y>>11)&255]+x)&MASK;output.append(b)
        self.a=a;self.b=b;self.results=output;self.position=255

    def word(self):
        if self.position<0:self.refill()
        value=self.results[self.position];self.position-=1
        return value

    def xor(self,blob,cancel=lambda:None):
        result=bytearray(len(blob))
        for start in range(0,len(blob),8):
            if not start%2048:cancel()
            key=self.word().to_bytes(8,'big')
            result[start:start+8]=bytes(a^b for a,b in zip(blob[start:start+8],key))
        return bytes(result)


def sns_variants(blob,keys,cancel=lambda:None):
    """Check a small prefix before spending time on a complete image stream."""
    from .media_codec import image_prefix,media_type
    for seed in list(dict.fromkeys(keys))[:8]:
        cancel()
        try:
            probe=Isaac64(seed).xor(blob[:32],cancel)
            if not image_prefix(probe) and not media_type(probe):continue
            yield Isaac64(seed).xor(blob,cancel)
        except ValueError:continue
