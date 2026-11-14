import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// src/core ships on its own: it may import packages and itself, nothing else.
const noRouter = { group: ['react-router-dom'], message: 'core must stay router-free.' }
const outside = (pattern) => ({
  group: [pattern],
  message: 'core must not import outside src/core.',
})

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // src/core is the reusable kernel: no routing, no fetching, no app state.
    files: ['src/core/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [noRouter, outside('../../*')] }],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/indigo-/], TemplateElement[value.raw=/indigo-/]',
          message: 'core reads accents from --qv-* tokens, not indigo-* utilities.',
        },
      ],
      'no-restricted-globals': [
        'error',
        { name: 'fetch', message: 'core must not fetch; the app passes data in.' },
      ],
    },
  },
  {
    // One level shallower: a file directly in src/core leaves it with '../'.
    files: ['src/core/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [noRouter, outside('../*')] }],
    },
  },
])
