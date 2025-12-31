import { useEffect, useState } from 'react';

let toastCallback = null;

export function toast(message, type = 'info') {
    if (toastCallback) {
        toastCallback(message, type);
    }
}

export default function Toast() {
    const [message, setMessage] = useState('');
    const [type, setType] = useState('info');
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        toastCallback = (msg, t) => {
            setMessage(msg);
            setType(t);
            setVisible(true);
            setTimeout(() => setVisible(false), 2200);
        };
        return () => { toastCallback = null; };
    }, []);

    if (!visible) return null;

    const bgColor = type === 'error' ? 'bg-red-600' : 'bg-gray-900';

    return (
        <div className={`fixed bottom-5 right-5 ${bgColor} text-white px-4 py-3 rounded-xl shadow-lg z-50 animate-slide-up`}>
            {message}
        </div>
    );
}