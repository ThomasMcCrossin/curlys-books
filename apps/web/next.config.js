/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  async redirects() {
    return [
      {
        // Redirect review.curlys.ca root to /review
        source: '/',
        has: [
          {
            type: 'host',
            value: 'review.curlys.ca',
          },
        ],
        destination: '/review',
        permanent: false,
      },
    ];
  },
};
module.exports = nextConfig;
