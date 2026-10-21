import type { NextConfig } from "next";

const config: NextConfig = {
  // The Docker image sets NEXT_OUTPUT_STANDALONE=1 at build time; local `next start` stays plain.
  output: process.env.NEXT_OUTPUT_STANDALONE ? "standalone" : undefined,
  poweredByHeader: false,
};

export default config;
