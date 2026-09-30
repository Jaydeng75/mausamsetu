import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  ...(process.env.VERCEL ? {} : {output: 'standalone' as const}),
  distDir: process.env.NODE_ENV === 'development' ? '.next-dev' : '.next',
  poweredByHeader: false,
  async headers(){
    return [{source:'/:path*',headers:[
      {key:'X-Content-Type-Options',value:'nosniff'},
      {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},
      {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'},
    ]}];
  },
};
export default nextConfig;
