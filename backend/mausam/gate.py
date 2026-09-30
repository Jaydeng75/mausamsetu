"""Optional learned gate. Requires the science extra; never auto-promoted."""
def create_gate(feature_count,source_count=4):
    import torch
    from torch import nn
    class ContextGate(nn.Module):
        def __init__(self):
            super().__init__();self.network=nn.Sequential(nn.Linear(feature_count,64),nn.ReLU(),nn.Linear(64,32),nn.ReLU(),nn.Linear(32,source_count))
        def forward(self,features,available):
            if not available.any(dim=-1).all():raise ValueError('No eligible sources')
            return torch.softmax(self.network(features).masked_fill(~available,float('-inf')),dim=-1)
    return ContextGate()

def train_candidate(features,samples,observations,available,output,epochs=100,seed=42):
    """Chronological input required. Optimizes exact empirical-mixture CRPS; saves a CANDIDATE."""
    import torch,json,hashlib
    from pathlib import Path
    torch.manual_seed(seed)
    x=torch.as_tensor(features,dtype=torch.float32);s=torch.as_tensor(samples,dtype=torch.float32);y=torch.as_tensor(observations,dtype=torch.float32);mask=torch.as_tensor(available,dtype=torch.bool)
    if not (x.shape[0]==s.shape[0]==y.shape[0]==mask.shape[0]):raise ValueError('Unaligned training samples')
    gate=create_gate(x.shape[1],s.shape[1]);optimizer=torch.optim.Adam(gate.parameters(),lr=.001)
    # Expect already calibrated, chronologically cross-fitted source distributions.
    first=(s-y[:,None,None]).abs().mean(dim=-1)
    pair=(s[:,:,None,:,None]-s[:,None,:,None,:]).abs().mean(dim=(-1,-2))
    for _ in range(epochs):
        w=gate(x,mask);loss=((w*first).sum(-1)-.5*torch.einsum('bi,bij,bj->b',w,pair,w)).mean();optimizer.zero_grad();loss.backward();optimizer.step()
    output=Path(output);output.mkdir(parents=True,exist_ok=False);torch.save(gate.state_dict(),output/'gate.pt')
    manifest={'status':'candidate','approved':False,'seed':seed,'epochs':epochs,'training_crps':float(loss.detach()),'feature_count':x.shape[1],'sha256':hashlib.sha256((output/'gate.pt').read_bytes()).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2));return manifest
