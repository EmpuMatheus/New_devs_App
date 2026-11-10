import React, { useEffect, useState } from 'react';
import { SecureAPI, RevenueSummaryResponse } from '../lib/secureApi';

export type RevenuePeriod =
    | { type: 'total' }
    | { type: 'monthly'; year: number; month: number }
    | { type: 'annual'; year: number };

interface RevenueSummaryProps {
    propertyId: string;
    period: RevenuePeriod;
    showRaw?: boolean;
}

const MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
];

const formatAmount = (amount: string): string => {
    const [whole, fraction] = amount.split('.');
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return fraction === undefined ? grouped : `${grouped}.${fraction}`;
};

export const RevenueSummary: React.FC<RevenueSummaryProps> = ({ propertyId, period, showRaw }) => {
    const [data, setData] = useState<RevenueSummaryResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const periodType = period.type;
    const periodYear = period.type === 'total' ? undefined : period.year;
    const periodMonth = period.type === 'monthly' ? period.month : undefined;

    useEffect(() => {
        let cancelled = false;

        const fetchRevenue = async () => {
            setLoading(true);
            setError('');
            try {
                let response: RevenueSummaryResponse;
                if (periodType === 'monthly') {
                    response = await SecureAPI.getMonthlyRevenue(propertyId, periodYear!, periodMonth!);
                } else if (periodType === 'annual') {
                    response = await SecureAPI.getAnnualRevenue(propertyId, periodYear!);
                } else {
                    response = await SecureAPI.getDashboardSummary(propertyId, {
                        timestamp: Date.now()
                    });
                }
                if (!cancelled) setData(response);
            } catch (err) {
                if (!cancelled) {
                    setData(null);
                    setError('Failed to load revenue data');
                    console.error(err);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        fetchRevenue();
        return () => { cancelled = true; };
    }, [propertyId, periodType, periodYear, periodMonth]);

    const periodLabel = periodType === 'monthly'
        ? `${MONTH_NAMES[periodMonth! - 1]} ${periodYear}`
        : periodType === 'annual'
            ? `Year ${periodYear}`
            : 'All time';

    if (loading) {
        return (
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                <div className="animate-pulse space-y-4">
                    <div className="h-4 bg-gray-100 rounded w-1/4"></div>
                    <div className="h-8 bg-gray-100 rounded w-1/2"></div>
                    <div className="flex gap-4 pt-4">
                        <div className="h-12 bg-gray-100 rounded flex-1"></div>
                    </div>
                </div>
            </div>
        );
    }

    if (error) return <div className="p-4 text-red-500 bg-red-50 rounded-lg">{error}</div>;
    if (!data) {
        return <div className="p-4 text-gray-500 bg-gray-50 rounded-lg">No revenue data available.</div>;
    }

    return (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden hover:shadow-md transition-shadow duration-300">
            {showRaw && (
                <div className="p-3 bg-gray-50 text-xs font-mono border-b border-gray-100 overflow-auto max-h-32">
                    <strong className="block mb-1 text-gray-500 uppercase tracking-wider text-[10px]">Raw API Response</strong>
                    <pre className="text-gray-700">{JSON.stringify(data, null, 2)}</pre>
                </div>
            )}

            <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide">
                            Total Revenue · {periodLabel}
                        </h2>
                        <div className="flex items-baseline gap-2 mt-1">
                            <span className="text-3xl font-bold text-gray-900 tracking-tight">
                                {data.currency} {formatAmount(data.total_revenue)}
                            </span>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-100">
                    <div>
                        <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Property ID</p>
                        <p className="text-sm font-semibold text-gray-700 font-mono mt-1">{data.property_id}</p>
                    </div>
                    <div>
                        <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Reservations</p>
                        <p className="text-sm font-semibold text-gray-700 mt-1">{data.reservations_count} <span className="font-normal text-gray-400">bookings</span></p>
                    </div>
                </div>

                <div className="mt-4 text-xs text-gray-400">
                    Exact recorded total: {data.currency} {formatAmount(data.total_revenue_exact)}
                    {data.timezone ? ` · ${data.timezone}` : ''}
                </div>
            </div>
        </div>
    );
};
