const path = require('path');
const CopyWebpackPlugin = require('copy-webpack-plugin');

module.exports = [
  // Main plugin bundle (Node.js target)
  {
    entry: './src/index.ts',
    output: {
      path: path.resolve(__dirname, 'dist'),
      filename: 'index.js',
      libraryTarget: 'commonjs2',
    },
    module: {
      rules: [
        {
          test: /\.tsx?$/,
          use: 'ts-loader',
          exclude: /node_modules/,
        },
      ],
    },
    resolve: {
      extensions: ['.ts', '.tsx', '.js', '.jsx'],
    },
    target: 'node',
  },
  // Content script bundle (browser target, IIFE)
  // Runs inside Joplin's editor webview for wiki-link rendering and autocomplete
  {
    entry: './src/content_script.ts',
    output: {
      path: path.resolve(__dirname, 'dist'),
      filename: 'content_script.js',
    },
    module: {
      rules: [
        {
          test: /\.tsx?$/,
          use: 'ts-loader',
          exclude: /node_modules/,
        },
      ],
    },
    resolve: {
      extensions: ['.ts', '.tsx', '.js', '.jsx'],
    },
    target: 'web',
  },
  // Graph view webview bundle (browser target)
  // Runs inside Joplin's panel webview for D3.js graph visualization
  {
    entry: './src/graph_view_bundle.ts',
    output: {
      path: path.resolve(__dirname, 'dist'),
      filename: 'graph_view_bundle.js',
    },
    module: {
      rules: [
        {
          test: /\.tsx?$/,
          use: 'ts-loader',
          exclude: /node_modules/,
        },
      ],
    },
    resolve: {
      extensions: ['.ts', '.tsx', '.js', '.jsx'],
    },
    target: 'web',
  },
];
