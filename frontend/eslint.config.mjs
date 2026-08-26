import nextVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextVitals,
  {
    ignores: [
      ".next/**",
      "coverage/**",
      "node_modules/**",
      "public/avatars/draco/**",
    ],
  },
];

export default eslintConfig;
