import js from "@eslint/js";
import globals from "globals";

/** @type {import('eslint').Linter.Config[]} */
export default [
  js.configs.recommended,
  {
    files: ["static/**/*.js"],
    languageOptions: {
      globals: {
        ...globals.browser,
        marked: "readonly",
        escapeHtml: "readonly",
        showToast: "readonly",
        renderMarkdown: "readonly",
        LabelPicker: "readonly",
        _reconnectSSE: "readonly",
        toggleNotifications: "readonly",
        dismissNotification: "readonly",
        dismissAllNotifications: "readonly",
      },
      ecmaVersion: 2022,
      sourceType: "script",
    },
    rules: {
      // Possible bugs
      "no-unused-vars": ["warn", { args: "none", vars: "all" }],
      "no-undef": "error",
      "no-redeclare": "error",
      "no-unreachable": "error",
      "no-fallthrough": "error",
      "no-constant-condition": "warn",
      // Best practices
      "eqeqeq": ["error", "always", { null: "ignore" }],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      "no-inner-declarations": "error",
      // Style
      "no-var": "warn",
      "prefer-const": "warn",
      "semi": ["error", "always"],
      "quotes": ["warn", "double", { avoidEscape: true }],
    },
  },
];
