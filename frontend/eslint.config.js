import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import importPlugin from 'eslint-plugin-import';
import boundaries from 'eslint-plugin-boundaries';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

const jsxA11yRules = jsxA11y.flatConfigs?.recommended?.rules ?? jsxA11y.configs.recommended.rules;
const reactHooksRules = reactHooks.configs.recommended.rules;

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'node_modules/**',
      // 静态资源（manifest / service worker / 图标）：原样发布，不参与 TS 工程与 lint
      'public/**',
      // 本机排查用的 playwright 脚本、截图（.gitignore 已忽略），不属于交付源码
      '.tmp/**',
      'src/shared/api/generated/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'jsx-a11y': jsxA11y,
      import: importPlugin,
      boundaries,
    },
    settings: {
      'import/resolver': {
        typescript: { project: ['./tsconfig.app.json'] },
      },
      'boundaries/include': ['src/**/*'],
      'boundaries/elements': [
        { type: 'app', pattern: 'src/app/**' },
        { type: 'feature', pattern: 'src/features/*', capture: ['feature'] },
        { type: 'shared', pattern: 'src/shared/**' },
        { type: 'styles', pattern: 'src/styles/**' },
        { type: 'test', pattern: 'src/test/**' },
      ],
    },
    rules: {
      ...reactHooksRules,
      // 页面级数据加载在 effect 内同步 setLoading 是既定模式；v7 该规则过严，这里关闭
      'react-hooks/set-state-in-effect': 'off',
      ...jsxA11yRules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'import/order': [
        'error',
        {
          groups: [
            'builtin',
            'external',
            'internal',
            'parent',
            'sibling',
            'index',
            'object',
            'type',
          ],
          'newlines-between': 'never',
          alphabetize: { order: 'asc', caseInsensitive: true },
        },
      ],
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          policies: [
            // app 可以用 feature 与 shared
            {
              from: { element: { type: 'app' } },
              allow: { to: { element: { types: { anyOf: ['feature', 'shared'] } } } },
            },
            // feature 之间只允许经 index.ts（由 entry-point 约束），可以自由用 shared
            {
              from: { element: { type: 'feature' } },
              allow: { to: { element: { types: { anyOf: ['shared', 'feature'] } } } },
            },
            {
              from: { element: { type: 'shared' } },
              allow: { to: { element: { type: 'shared' } } },
            },
            {
              from: { element: { type: 'test' } },
              allow: { to: { element: { types: { anyOf: ['shared', 'feature', 'app'] } } } },
            },
            {
              from: { element: { type: 'styles' } },
              allow: { to: { element: { type: 'shared' } } },
            },
          ],
        },
      ],
      'boundaries/entry-point': [
        'error',
        {
          default: 'disallow',
          policies: [
            // feature 只能被 index.ts 引用（跨 feature 边界）
            { target: { element: { type: 'feature' } }, allow: ['index.ts'] },
            { target: { element: { type: 'shared' } }, allow: ['**'] },
            { target: { element: { type: 'app' } }, allow: ['**'] },
            { target: { element: { type: 'styles' } }, allow: ['**'] },
          ],
        },
      ],
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'separate-type-imports' },
      ],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  {
    files: ['*.config.{ts,js}', 'scripts/**/*.{mjs,cjs,js}', 'e2e/**/*.ts'],
    languageOptions: {
      // 巡检脚本用 node 跑，但 page.evaluate 的回调体是在浏览器里执行的（document 等）
      globals: { ...globals.node, ...globals.browser },
    },
    rules: {
      // .cjs 脚本只能 require：Node 在 CJS 下不认 ESM import，这条规则对它们无解
      '@typescript-eslint/no-require-imports': 'off',
    },
  },
  {
    // 测试文件放宽两条规则：
    // - `vi.mock('x', async (orig) => orig<typeof import('x')>())` 是 vitest 官方推荐的
    //   保留原实现写法，这里的 import() 只作类型标注用，无法改成 type-import；
    // - 断言处偶尔需要 `as unknown as T` 之类的双重断言绕过 mock 类型。
    files: ['**/*.test.{ts,tsx}', 'src/test/**/*.ts'],
    rules: {
      '@typescript-eslint/consistent-type-imports': [
        'error',
        {
          prefer: 'type-imports',
          fixStyle: 'separate-type-imports',
          disallowTypeAnnotations: false,
        },
      ],
    },
  },
  prettier,
);
