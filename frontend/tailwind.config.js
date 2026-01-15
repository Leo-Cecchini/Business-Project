/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,jsx}",
    ],
    theme: {
        extend: {
            colors: {
                brand: '#3b5bfd',
                border: '#e5e7eb',
                muted: '#6b7280',
            }
        },
    },
    plugins: [],
}