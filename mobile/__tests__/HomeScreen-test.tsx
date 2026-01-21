import { render, screen } from '@testing-library/react-native';
import IndexScreen from '../app/index';

describe('<IndexScreen />', () => {
  it('renders loading indicator', () => {
    render(<IndexScreen />);
    // Index screen shows a loading indicator while determining redirect
    expect(screen.getByTestId('activity-indicator')).toBeTruthy();
  });
});
