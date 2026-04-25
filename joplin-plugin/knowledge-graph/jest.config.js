module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src'],
  testMatch: ['**/__tests__/**/*.test.ts'],
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  moduleNameMapper: {
    '^joplin-api$': '<rootDir>/src/__tests__/__mocks__/joplin-api.ts',
    '^joplin/plugins$': '<rootDir>/src/__tests__/__mocks__/joplin-plugins.ts',
  },
};
